# A real Minecraft client with no screen and no GPU, for tests that need what players actually see.
# Xvfb is the virtual display and Mesa's llvmpipe renders in software, which is slow but accurate.
FROM eclipse-temurin:25-jdk

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      xvfb xauth mesa-utils libgl1 libgl1-mesa-dri libegl1 libegl-mesa0 libglx-mesa0 libopengl0 libglu1-mesa \
      libx11-6 libxext6 libxrandr2 libxrender1 libxcursor1 libxi6 libxinerama1 libxxf86vm1 libxtst6 \
      libasound2t64 libopenal1 libpulse0 \
 && rm -rf /var/lib/apt/lists/*
