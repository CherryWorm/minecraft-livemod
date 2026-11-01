#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:globals.glsl>

layout(location = 0) in vec2 texCoord;
layout(location = 1) in vec4 vertexColor;

layout(location = 0) out vec4 fragColor;

void main() {
    vec2 centred = texCoord - 0.5;
    if (length(centred) > 0.5) {
        discard;
    }
    float ring = 0.5 + 0.5 * sin(length(centred) * 40.0 - GameTime * 24000.0);
    fragColor = vec4(0.1, 0.2 + 0.7 * ring, 1.0, 0.95) * vertexColor;
}
