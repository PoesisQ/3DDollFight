#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <astra/capi/astra.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
volatile LONG running = 1;
BOOL WINAPI stop(DWORD) { InterlockedExchange(&running, 0); return TRUE; }
bool isRunning() { return InterlockedCompareExchange(&running, 1, 1) != 0; }
void check(astra_status_t rc, const char* operation) {
    if (rc != ASTRA_STATUS_SUCCESS)
        throw std::runtime_error(std::string(operation) + " failed (Astra status " + std::to_string(rc) + ")");
}
struct Sensor {
    bool initialized = false;
    astra_streamsetconnection_t sensor = nullptr;
    astra_reader_t reader = nullptr;
    astra_bodystream_t body = nullptr;
    astra_colorstream_t color = nullptr;
    ~Sensor() {
        if (color) astra_stream_stop(color);
        if (body) astra_stream_stop(body);
        if (reader) astra_reader_destroy(&reader);
        if (sensor) astra_streamset_close(&sensor);
        if (initialized) astra_terminate();
    }
    void open(const std::string& licensePath, const std::string& uri = "device/default",
              bool initialize = true, bool withColor = false) {
        if (initialize) { check(astra_initialize(), "astra_initialize"); initialized = true; }
        if (initialize && !licensePath.empty()) {
            std::ifstream f(licensePath, std::ios::binary);
            if (!f) throw std::runtime_error("Cannot read license file");
            std::string key((std::istreambuf_iterator<char>(f)), {});
            if (key.compare(0, 3, "\xef\xbb\xbf") == 0) key.erase(0, 3);
            auto first = key.find_first_not_of(" \t\r\n");
            auto last = key.find_last_not_of(" \t\r\n");
            if (first == std::string::npos) throw std::runtime_error("License file is empty");
            key = key.substr(first, last - first + 1);
            check(orbbec_body_tracking_set_license(key.c_str()), "body license");
        } else if (initialize) std::cout << "Using the SDK built-in trial.\n";
        check(astra_streamset_open(uri.c_str(), &sensor), "streamset_open");
        bool available = false;
        check(astra_streamset_is_available(sensor, &available), "streamset_is_available");
        if (!available) throw std::runtime_error("Camera " + uri + " is unavailable. Connect the Astra camera and close other viewers.");
        check(astra_reader_create(sensor, &reader), "reader_create");
        check(astra_reader_get_bodystream(reader, &body), "get_bodystream");
        if (withColor) check(astra_reader_get_colorstream(reader, &color), "get_colorstream");
        check(astra_bodystream_set_default_body_features(body, ASTRA_BODY_TRACKING_JOINTS), "set_joint_features");
        check(astra_bodystream_set_skeleton_profile(body, ASTRA_SKELETON_PROFILE_FULL), "set_full_skeleton");
        check(astra_stream_start(body), "stream_start");
        if (withColor) check(astra_stream_start(color), "start_color");
    }
};
struct Socket {
    SOCKET value = INVALID_SOCKET;
    bool initialized = false;
    sockaddr_in target{};
    ~Socket() { if (value != INVALID_SOCKET) closesocket(value); if (initialized) WSACleanup(); }
    void open(const std::string& host, int port) {
        WSADATA data{};
        if (WSAStartup(MAKEWORD(2, 2), &data)) throw std::runtime_error("WSAStartup failed");
        initialized = true;
        target.sin_family = AF_INET; target.sin_port = htons(static_cast<u_short>(port));
        if (inet_pton(AF_INET, host.c_str(), &target.sin_addr) != 1)
            throw std::runtime_error("--host must be an IPv4 address");
        value = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (value == INVALID_SOCKET) throw std::runtime_error("Cannot create UDP socket");
    }
    void send(const std::string& json) {
        if (json.size() > 60000) throw std::runtime_error("Skeleton packet exceeds 60000 bytes");
        if (sendto(value, json.data(), static_cast<int>(json.size()), 0,
                   reinterpret_cast<const sockaddr*>(&target), sizeof(target)) == SOCKET_ERROR)
            throw std::runtime_error("UDP send failed: " + std::to_string(WSAGetLastError()));
    }
};
struct ColorFeed {
    struct Frame {
        std::vector<uint8_t> rgb;
        uint32_t width = 0, height = 0, index = 0;
        uint64_t timestamp = 0;
        bool fresh = false;
    };
    SOCKET listener = INVALID_SOCKET;
    std::thread worker;
    std::mutex gate;
    std::condition_variable changed;
    Frame latest;
    std::atomic<bool> connected{false};
    bool active = false;

    ~ColorFeed() { close(); }

    void open(int port) {
        listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (listener == INVALID_SOCKET) throw std::runtime_error("Cannot create color socket");
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(static_cast<u_short>(port));
        inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
        if (bind(listener, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) == SOCKET_ERROR)
            throw std::runtime_error("Cannot bind color port " + std::to_string(port));
        if (listen(listener, 1) == SOCKET_ERROR)
            throw std::runtime_error("Cannot listen on color port " + std::to_string(port));
        active = true;
        worker = std::thread([this] { acceptLoop(); });
    }

    void close() {
        if (!active) return;
        active = false;
        changed.notify_all();
        if (listener != INVALID_SOCKET) { closesocket(listener); listener = INVALID_SOCKET; }
        if (worker.joinable()) worker.join();
    }

    // Called from the capture loop. Copies only while a tracker is attached.
    void publish(const uint8_t* data, uint32_t width, uint32_t height, uint32_t index, uint64_t timestamp) {
        if (!connected.load()) return;
        std::lock_guard<std::mutex> lock(gate);
        latest.rgb.assign(data, data + static_cast<size_t>(width) * height * 3);
        latest.width = width; latest.height = height;
        latest.index = index; latest.timestamp = timestamp; latest.fresh = true;
        changed.notify_one();
    }

    void acceptLoop() {
        while (active) {
            SOCKET peer = accept(listener, nullptr, nullptr);
            if (peer == INVALID_SOCKET) {
                if (!active) break;
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                continue;
            }
            DWORD timeout = 2000;
            setsockopt(peer, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
            connected = true;
            serve(peer);
            connected = false;
            closesocket(peer);
        }
    }

    void serve(SOCKET peer) {
        Frame outgoing;
        while (active) {
            {
                std::unique_lock<std::mutex> lock(gate);
                changed.wait_for(lock, std::chrono::milliseconds(100), [this] { return latest.fresh || !active; });
                if (!active) return;
                if (!latest.fresh) continue;
                outgoing = latest;
                latest.fresh = false;
            }
            uint8_t header[24];
            std::memcpy(header, "DFCF", 4);
            store(header + 4, outgoing.width);
            store(header + 8, outgoing.height);
            store(header + 12, outgoing.index);
            store(header + 16, static_cast<uint32_t>(outgoing.timestamp & 0xffffffffull));
            store(header + 20, static_cast<uint32_t>(outgoing.timestamp >> 32));
            if (!sendAll(peer, header, sizeof(header))) return;
            if (!outgoing.rgb.empty() && !sendAll(peer, outgoing.rgb.data(), outgoing.rgb.size())) return;
        }
    }

    static void store(uint8_t* target, uint32_t value) {
        target[0] = static_cast<uint8_t>(value & 0xff);
        target[1] = static_cast<uint8_t>((value >> 8) & 0xff);
        target[2] = static_cast<uint8_t>((value >> 16) & 0xff);
        target[3] = static_cast<uint8_t>((value >> 24) & 0xff);
    }

    static bool sendAll(SOCKET peer, const uint8_t* data, size_t size) {
        size_t sent = 0;
        while (sent < size) {
            int chunk = send(peer, reinterpret_cast<const char*>(data + sent),
                             static_cast<int>(std::min<size_t>(size - sent, 65536)), 0);
            if (chunk <= 0) return false;
            sent += static_cast<size_t>(chunk);
        }
        return true;
    }
};
float finite(float x) { return std::isfinite(x) ? x : 0.f; }
void vec(std::ostream& o, astra_vector3f_t p) {
    o << "{\"x\":" << finite(p.x) << ",\"y\":" << finite(p.y) << ",\"z\":" << finite(p.z) << '}';
}
std::string packet(const astra_body_list_t& list, long long sequence, int sourceFrame,
                   const std::string& session, long long timestamp, bool simulated) {
    std::ostringstream o; o.imbue(std::locale::classic()); o << std::fixed << std::setprecision(3);
    o << "{\"version\":1,\"session\":\"" << session << "\",\"sequence\":" << sequence
      << ",\"sourceFrame\":" << sourceFrame << ",\"timestampMs\":" << timestamp
      << ",\"simulated\":" << (simulated ? "true" : "false") << ",\"units\":\"mm\",\"bodies\":[";
    for (int i = 0; i < std::clamp(list.count, 0, ASTRA_MAX_BODIES); ++i) {
        if (i) o << ',';
        const auto& b = list.bodies[i];
        const bool tracked = b.status == ASTRA_BODY_STATUS_TRACKING || b.status == ASTRA_BODY_STATUS_TRACKING_STARTED;
        const bool hasJoints = tracked && (b.features & ASTRA_BODY_TRACKING_JOINTS);
        o << "{\"id\":" << int(b.id) << ",\"status\":" << int(b.status) << ",\"joints\":[";
        for (int j = 0; j < ASTRA_MAX_JOINTS; ++j) {
            if (j) o << ',';
            const auto& joint = b.joints[j];
            const auto p = joint.worldPosition;
            const bool valid = hasJoints && std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
            o << "{\"type\":" << j << ",\"status\":" << (valid ? int(joint.status) : 0) << ",\"position\":";
            vec(o, valid ? p : astra_vector3f_t{});
            const auto& r = joint.orientation;
            o << ",\"orientation\":[" << finite(r.m00) << ',' << finite(r.m01) << ',' << finite(r.m02)
              << ',' << finite(r.m10) << ',' << finite(r.m11) << ',' << finite(r.m12)
              << ',' << finite(r.m20) << ',' << finite(r.m21) << ',' << finite(r.m22) << "]}";
        }
        o << "]}";
    }
    o << "]}"; return o.str();
}
astra_body_list_t simulate(double seconds, double warmup = 2.0) {
    // First two seconds: T pose for calibration. Then bend/lift both arms.
    astra_body_list_t list{}; list.count = 1;
    auto& b = list.bodies[0]; b.id = 1; b.status = ASTRA_BODY_STATUS_TRACKING; b.features = ASTRA_BODY_TRACKING_JOINTS;
    astra_vector3f_t p[ASTRA_MAX_JOINTS] = {
        {0,750,2000},{0,500,2000},{-230,500,2000},{-520,500,2000},{-870,500,2000},
        {230,500,2000},{520,500,2000},{870,500,2000},{0,250,2000},{0,0,2000},
        {-130,-30,2000},{-130,-460,2000},{-130,-890,2000},
        {130,-30,2000},{130,-460,2000},{130,-890,2000},
        {-790,500,2000},{790,500,2000},{0,600,2000}};
    const double t = std::max(0., seconds - warmup);
    const float angle = static_cast<float>(0.8 * std::sin(t * 1.5));
    for (int id : {3,4,16,6,7,17}) {
        const int shoulder = (id == 3 || id == 4 || id == 16) ? 2 : 5;
        const float sign = shoulder == 2 ? -1.f : 1.f;
        const float length = std::abs(p[id].x - p[shoulder].x);
        p[id].x = p[shoulder].x + sign * length * std::cos(angle);
        p[id].y += length * std::sin(angle);
    }
    for (int j = 0; j < ASTRA_MAX_JOINTS; ++j) {
        auto& joint = b.joints[j]; joint.type = static_cast<uint8_t>(j);
        joint.status = ASTRA_JOINT_STATUS_TRACKED; joint.worldPosition = p[j];
        joint.orientation.m00 = joint.orientation.m11 = joint.orientation.m22 = 1;
    }
    return list;
}
int number(const std::string& text) {
    size_t end = 0; int n = std::stoi(text, &end);
    if (end != text.size()) throw std::runtime_error("Invalid integer: " + text);
    return n;
}
}
int main(int argc, char** argv) {
    try {
        bool simulated = false, dual = false; int port = 7001, frames = 0, warmup = 2, colorPort = 0, mirrorPort = 0;
        std::string host = "127.0.0.1", license;
        for (int i = 1; i < argc; ++i) {
            std::string option = argv[i];
            if (option == "--help") {
                std::cout << "AstraUnityBridge [--dual] [--simulate] [--warmup seconds] [--host IPv4] [--port 7001]"
                             " [--frames N] [--license FILE] [--color-port 7005] [--mirror-port 7012]\n"; return 0;
            }
            if (option == "--simulate") { simulated = true; continue; }
            if (option == "--dual") { dual = true; continue; }
            if (i + 1 >= argc) throw std::runtime_error("Missing value for " + option);
            std::string value = argv[++i];
            if (option == "--host") host = value;
            else if (option == "--port") port = number(value);
            else if (option == "--frames") frames = number(value);
            else if (option == "--warmup") warmup = number(value);
            else if (option == "--license") license = value;
            else if (option == "--color-port") colorPort = number(value);
            else if (option == "--mirror-port") mirrorPort = number(value);
            else throw std::runtime_error("Unknown option " + option);
        }
        if (port < 1 || port > (dual ? 65534 : 65535) || frames < 0 || warmup < 0 || warmup > 60) throw std::runtime_error("Invalid port, frame count or warmup");
        if (colorPort && (dual || simulated)) throw std::runtime_error("--color-port works with a single live camera only");
        if (mirrorPort && (dual || simulated)) throw std::runtime_error("--mirror-port works with a single live camera only");
        if (mirrorPort && mirrorPort == port) throw std::runtime_error("--mirror-port must differ from --port");
        SetConsoleCtrlHandler(stop, TRUE);
        Socket socket; socket.open(host, port);
        Socket socket2; if (dual) socket2.open(host, port + 1);
        Socket mirror; if (mirrorPort) { mirror.open(host, mirrorPort); std::cout << "Body mirror -> " << host << ':' << mirrorPort << '\n'; }
        Sensor sensor, sensor2;
        if (!simulated) {
            sensor.open(license, dual ? "device/sensor0" : "device/default", true, colorPort != 0);
            if (dual) sensor2.open("", "device/sensor1", false);
        }
        ColorFeed color;
        if (colorPort) {
            color.open(colorPort);
            std::cout << "COLOR RGB -> 127.0.0.1:" << colorPort << '\n';
        }
        auto start = std::chrono::steady_clock::now();
        auto lastFrame = start;
        const std::string session = std::to_string(GetCurrentProcessId()) + "-" + std::to_string(
            std::chrono::system_clock::now().time_since_epoch().count());
        std::cout << (simulated ? "SIMULATED" : "LIVE ASTRA") << " -> " << host << ':' << port << ". Ctrl+C stops.\n";
        if (dual) {
            std::cout << "Second camera -> " << host << ':' << port + 1 << '\n';
            long long counts[2] = {0, 0};
            auto lastFrames = std::array<std::chrono::steady_clock::time_point, 2>{start, start};
            while (isRunning() && (!frames || counts[0] < frames || counts[1] < frames)) {
                auto now = std::chrono::steady_clock::now();
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - start).count();
                if (!simulated) check(astra_update(), "astra_update");
                for (int i = 0; i < 2; ++i) {
                    if (frames && counts[i] >= frames) continue;
                    astra_body_list_t bodies{};
                    astra_frame_index_t index = static_cast<int>(counts[i]);
                    if (simulated) bodies = simulate(elapsed / 1000. + i * 0.5, warmup);
                    else {
                        astra_reader_frame_t frame = nullptr;
                        auto rc = astra_reader_open_frame(i == 0 ? sensor.reader : sensor2.reader, 0, &frame);
                        if (rc == ASTRA_STATUS_TIMEOUT) {
                            if (now - lastFrames[i] > std::chrono::seconds(10))
                                throw std::runtime_error("Camera sensor" + std::to_string(i) + " has no body frames for 10 seconds. Check the camera, USB and license.");
                            continue;
                        }
                        check(rc, "reader_open_frame");
                        astra_bodyframe_t bodyFrame = nullptr;
                        rc = astra_frame_get_bodyframe(frame, &bodyFrame);
                        if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_get_frameindex(bodyFrame, &index);
                        if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_body_list(bodyFrame, &bodies);
                        astra_reader_close_frame(&frame);
                        check(rc, "read_body_frame");
                        lastFrames[i] = now;
                    }
                    (i == 0 ? socket : socket2).send(packet(bodies, counts[i], index, session, elapsed, simulated));
                    ++counts[i];
                }
                if (simulated) std::this_thread::sleep_until(start + std::chrono::milliseconds(counts[0] * 1000 / 30));
                else std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
            std::cout << "Stopped. Camera frames: " << counts[0] << ", " << counts[1] << '\n';
            return 0;
        }
        long long sequence = 0;
        while (isRunning() && (!frames || sequence < frames)) {
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - start).count();
            astra_body_list_t bodies{}; astra_frame_index_t index = static_cast<int>(sequence);
            if (simulated) bodies = simulate(elapsed / 1000., warmup);
            else {
                check(astra_update(), "astra_update");
                astra_reader_frame_t frame = nullptr;
                auto rc = astra_reader_open_frame(sensor.reader, 0, &frame);
                if (rc == ASTRA_STATUS_TIMEOUT) {
                    if (now - lastFrame > std::chrono::seconds(10)) throw std::runtime_error("No body frames for 10 seconds. Check camera, USB, and SDK license.");
                    std::this_thread::sleep_for(std::chrono::milliseconds(2)); continue;
                }
                check(rc, "reader_open_frame");
                if (colorPort) {
                    astra_colorframe_t colorFrame = nullptr;
                    if (astra_frame_get_colorframe(frame, &colorFrame) == ASTRA_STATUS_SUCCESS) {
                        astra_image_metadata_t metadata{};
                        astra_rgb_pixel_t* pixels = nullptr;
                        uint32_t byteLength = 0;
                        astra_frame_index_t colorIndex = 0;
                        if (astra_colorframe_get_metadata(colorFrame, &metadata) == ASTRA_STATUS_SUCCESS &&
                            astra_colorframe_get_data_rgb_ptr(colorFrame, &pixels, &byteLength) == ASTRA_STATUS_SUCCESS &&
                            pixels != nullptr &&
                            byteLength >= static_cast<uint32_t>(metadata.width) * metadata.height * 3) {
                            astra_colorframe_get_frameindex(colorFrame, &colorIndex);
                            color.publish(reinterpret_cast<const uint8_t*>(pixels), metadata.width, metadata.height,
                                          static_cast<uint32_t>(colorIndex), static_cast<uint64_t>(elapsed));
                        }
                    }
                }
                astra_bodyframe_t bodyFrame = nullptr;
                rc = astra_frame_get_bodyframe(frame, &bodyFrame);
                if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_get_frameindex(bodyFrame, &index);
                if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_body_list(bodyFrame, &bodies);
                astra_reader_close_frame(&frame);
                // With the colour stream running, a frame may carry colour only.
                if (rc != ASTRA_STATUS_SUCCESS && !colorPort) check(rc, "read_body_frame");
                if (rc != ASTRA_STATUS_SUCCESS) {
                    if (now - lastFrame > std::chrono::seconds(10)) throw std::runtime_error("No body frames for 10 seconds. Check camera, USB, and SDK license.");
                    continue;
                }
                lastFrame = now;
            }
            const std::string json = packet(bodies, sequence, index, session, elapsed, simulated);
            socket.send(json);
            if (mirrorPort) mirror.send(json);
            if (sequence % 150 == 0) std::cout << "Frame " << sequence << ", bodies: " << bodies.count << '\n';
            ++sequence;
            if (simulated) std::this_thread::sleep_until(start + std::chrono::milliseconds(sequence * 1000 / 30));
        }
        std::cout << "Stopped after " << sequence << " frames.\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << "ERROR: " << e.what() << '\n'; return 1; }
}
