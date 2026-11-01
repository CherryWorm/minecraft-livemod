package gm.feature.protected_mixin.mixin;

import net.minecraft.server.MinecraftServer;
import net.minecraft.world.level.chunk.LevelChunk;
import org.spongepowered.asm.mixin.Mixin;

@Mixin({MinecraftServer.class, LevelChunk.class})
abstract class ServerMixin {
}
