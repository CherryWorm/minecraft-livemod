package gm.conduit.retrogen;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.core.QuartPos;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.chunk.ChunkAccess;
import net.minecraft.world.level.chunk.LevelChunk;

import java.util.ArrayList;
import java.util.List;

/**
 * A module changing the climate of a piece of land for good. A chunk keeps its biomes with its blocks, so this saves with it and
 * survives a restart, and players see it straight away. Nothing is placed or moved, so a chunk's blocks and their records stay as they were.
 */
public final class LastingClimate {
	private LastingClimate() {}

	/** How many cells of the game's biome grid changed, or -1 if some of the land isn't loaded, in which case nothing did. */
	public static int setBiome(ServerLevel level, BlockPos from, BlockPos to, String biome) {
		Holder<Biome> target = level.registryAccess().lookupOrThrow(Registries.BIOME).get(ResourceKey.create(Registries.BIOME, Identifier.parse(biome)))
				.orElseThrow(() -> new IllegalArgumentException("There's no biome called " + biome));
		int minX = QuartPos.fromBlock(Math.min(from.getX(), to.getX()));
		int minY = QuartPos.fromBlock(Math.min(from.getY(), to.getY()));
		int minZ = QuartPos.fromBlock(Math.min(from.getZ(), to.getZ()));
		int maxX = QuartPos.fromBlock(Math.max(from.getX(), to.getX()));
		int maxY = QuartPos.fromBlock(Math.max(from.getY(), to.getY()));
		int maxZ = QuartPos.fromBlock(Math.max(from.getZ(), to.getZ()));
		List<LevelChunk> chunks = new ArrayList<>();
		for (int x = minX >> 2; x <= maxX >> 2; x++) {
			for (int z = minZ >> 2; z <= maxZ >> 2; z++) {
				LevelChunk chunk = level.getChunkSource().getChunkNow(x, z);
				if (chunk == null) {
					return -1;
				}
				chunks.add(chunk);
			}
		}
		int[] changed = {0};
		List<ChunkAccess> touched = new ArrayList<>();
		for (LevelChunk chunk : chunks) {
			int before = changed[0];
			chunk.fillBiomesFromNoise((x, y, z) -> {
				Holder<Biome> existing = chunk.getNoiseBiome(x, y, z);
				if (x < minX || x > maxX || y < minY || y > maxY || z < minZ || z > maxZ || existing.equals(target)) {
					return existing;
				}
				changed[0]++;
				return target;
			});
			if (changed[0] != before) {
				chunk.markUnsaved();
				touched.add(chunk);
			}
		}
		if (!touched.isEmpty()) {
			level.getChunkSource().chunkMap.resendBiomesForChunks(touched);
		}
		return changed[0];
	}
}
