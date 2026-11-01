#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:globals.glsl>

uniform sampler2D SceneSampler;

layout(location = 0) in vec2 texCoord;

layout(location = 0) out vec4 fragColor;

void main() {
    vec2 here = gl_FragCoord.xy / ScreenSize;
    vec2 bent = here + vec2(0.0, sin(texCoord.x * 30.0 + GameTime * 12000.0) * 0.03);
    fragColor = vec4(texture(SceneSampler, bent).rgb, 1.0);
}
