#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:globals.glsl>

uniform sampler2D InSampler;

layout(location = 0) in vec2 texCoord;
layout(location = 0) out vec4 fragColor;

// Turns the picture inside out, so it's easy to see from a screenshot, but only if it can really read the game's clock.
void main() {
    vec3 seen = texture(InSampler, texCoord).rgb;
    fragColor = vec4(GameTime > 0.0 ? 1.0 - seen : seen, 1.0);
}
