Shader "DollFight/Soft Contact Shadow"
{
    Properties { _MainTex ("Falloff", 2D) = "white" {} _Color ("Tint", Color) = (0,0,0,0.3) }
    SubShader
    {
        Tags { "Queue"="Transparent-20" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZWrite Off
        Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex; fixed4 _Color;
            struct v2f { float4 position : SV_POSITION; float2 uv : TEXCOORD0; };
            v2f vert(appdata_base v) { v2f o; o.position = UnityObjectToClipPos(v.vertex); o.uv = v.texcoord; return o; }
            fixed4 frag(v2f i) : SV_Target { return fixed4(_Color.rgb, _Color.a * tex2D(_MainTex, i.uv).a); }
            ENDCG
        }
    }
}
