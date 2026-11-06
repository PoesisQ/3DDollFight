#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <astra/capi/astra.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

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
    ~Sensor() {
        if (body) astra_stream_stop(body);
        if (reader) astra_reader_destroy(&reader);
        if (sensor) astra_streamset_close(&sensor);
        if (initialized) astra_terminate();
    }
    void open(const std::string& licensePath, const std::string& uri = "device/default", bool initialize = true) {
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
        check(astra_bodystream_set_default_body_features(body, ASTRA_BODY_TRACKING_JOINTS), "set_joint_features");
        check(astra_bodystream_set_skeleton_profile(body, ASTRA_SKELETON_PROFILE_FULL), "set_full_skeleton");
        check(astra_stream_start(body), "stream_start");
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
astra_body_list_t simulate(double seconds) {
    // First two seconds: T pose for calibration. Then bend/lift both arms.
    astra_body_list_t list{}; list.count = 1;
    auto& b = list.bodies[0]; b.id = 1; b.status = ASTRA_BODY_STATUS_TRACKING; b.features = ASTRA_BODY_TRACKING_JOINTS;
    astra_vector3f_t p[ASTRA_MAX_JOINTS] = {
        {0,750,2000},{0,500,2000},{-230,500,2000},{-520,500,2000},{-870,500,2000},
        {230,500,2000},{520,500,2000},{870,500,2000},{0,250,2000},{0,0,2000},
        {-130,-30,2000},{-130,-460,2000},{-130,-890,2000},
        {130,-30,2000},{130,-460,2000},{130,-890,2000},
        {-790,500,2000},{790,500,2000},{0,600,2000}};
    const double t = std::max(0., seconds - 2.);
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
        bool simulated = false, dual = false; int port = 7001, frames = 0;
        std::string host = "127.0.0.1", license;
        for (int i = 1; i < argc; ++i) {
            std::string option = argv[i];
            if (option == "--help") {
                std::cout << "AstraUnityBridge [--dual] [--simulate] [--host IPv4] [--port 7001] [--frames N] [--license FILE]\n"; return 0;
            }
            if (option == "--simulate") { simulated = true; continue; }
            if (option == "--dual") { dual = true; continue; }
            if (i + 1 >= argc) throw std::runtime_error("Missing value for " + option);
            std::string value = argv[++i];
            if (option == "--host") host = value;
            else if (option == "--port") port = number(value);
            else if (option == "--frames") frames = number(value);
            else if (option == "--license") license = value;
            else throw std::runtime_error("Unknown option " + option);
        }
        if (port < 1 || port > (dual ? 65534 : 65535) || frames < 0) throw std::runtime_error("Invalid port or frame count");
        SetConsoleCtrlHandler(stop, TRUE);
        Socket socket; socket.open(host, port);
        Socket socket2; if (dual) socket2.open(host, port + 1);
        Sensor sensor, sensor2;
        if (!simulated) {
            sensor.open(license, dual ? "device/sensor0" : "device/default");
            if (dual) sensor2.open("", "device/sensor1", false);
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
                    if (simulated) bodies = simulate(elapsed / 1000. + i * 0.5);
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
            if (simulated) bodies = simulate(elapsed / 1000.);
            else {
                check(astra_update(), "astra_update");
                astra_reader_frame_t frame = nullptr;
                auto rc = astra_reader_open_frame(sensor.reader, 0, &frame);
                if (rc == ASTRA_STATUS_TIMEOUT) {
                    if (now - lastFrame > std::chrono::seconds(10)) throw std::runtime_error("No body frames for 10 seconds. Check camera, USB, and SDK license.");
                    std::this_thread::sleep_for(std::chrono::milliseconds(2)); continue;
                }
                check(rc, "reader_open_frame");
                astra_bodyframe_t bodyFrame = nullptr;
                rc = astra_frame_get_bodyframe(frame, &bodyFrame);
                if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_get_frameindex(bodyFrame, &index);
                if (rc == ASTRA_STATUS_SUCCESS) rc = astra_bodyframe_body_list(bodyFrame, &bodies);
                astra_reader_close_frame(&frame);
                check(rc, "read_body_frame");
                lastFrame = now;
            }
            socket.send(packet(bodies, sequence, index, session, elapsed, simulated));
            if (sequence % 150 == 0) std::cout << "Frame " << sequence << ", bodies: " << bodies.count << '\n';
            ++sequence;
            if (simulated) std::this_thread::sleep_until(start + std::chrono::milliseconds(sequence * 1000 / 30));
        }
        std::cout << "Stopped after " << sequence << " frames.\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << "ERROR: " << e.what() << '\n'; return 1; }
}
