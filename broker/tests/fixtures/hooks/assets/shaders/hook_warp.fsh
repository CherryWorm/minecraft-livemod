#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:globals.glsl>

uniform sampler2D InSampler;

layout(location = 0) in vec2 texCoord;
layout(location = 0) out vec4 fragColor;

// Turns the picture inside out, so it's easy to see from a screenshot. The time is read to prove that it can be.
void main() {
    vec2 shifted = texCoord + vec2(sin(GameTime * 6283.0) * 0.001, 0.0);
    fragColor = vec4(1.0 - texture(InSampler, shifted).rgb, 1.0);
}
