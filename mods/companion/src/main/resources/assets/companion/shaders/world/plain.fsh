#version 330
#extension GL_ARB_separate_shader_objects : require

#include <minecraft:fog.glsl>

uniform sampler2D Sampler0;

layout(location = 0) in vec2 texCoord;
layout(location = 1) in vec4 vertexColor;
layout(location = 2) in vec3 fromCamera;

layout(location = 0) out vec4 fragColor;

void main() {
    vec4 color = texture(Sampler0, texCoord) * vertexColor;
    if (color.a < 0.004) {
        discard;
    }
    // Worked out here rather than at the corners, because something big would otherwise come out all the colour of the fog.
    #ifdef NO_FOG
    fragColor = color;
    #else
    fragColor = apply_fog(color, fog_spherical_distance(fromCamera), fog_cylindrical_distance(fromCamera), FogEnvironmentalStart, FogEnvironmentalEnd, FogRenderDistanceStart, FogRenderDistanceEnd, FogColor);
    #endif
}
