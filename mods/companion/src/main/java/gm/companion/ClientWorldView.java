package gm.companion;

import gm.companion.api.WorldView;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.SectionPos;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.ChunkAccess;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.level.material.MapColor;

/** The one part of the player and the level that modules get, as plain numbers and text, so they never hold anything that can act as the player. */
final class ClientWorldView implements WorldView {
	private static final int MOST_LIGHT = 15;
	private static final int CHUNK_MASK = 15;
	private static final long MOST_MAP_PIXELS = 1L << 20;

	private final BlockPos.MutableBlockPos place = new BlockPos.MutableBlockPos();

	private static ClientLevel level() {
		return Minecraft.getInstance().level;
	}

	private static LocalPlayer player() {
		return Minecraft.getInstance().player;
	}

	@Override
	public boolean inWorld() {
		return level() != null && player() != null;
	}

	@Override
	public double playerX() {
		return inWorld() ? player().getX() : 0;
	}

	@Override
	public double playerY() {
		return inWorld() ? player().getY() : 0;
	}

	@Override
	public double playerZ() {
		return inWorld() ? player().getZ() : 0;
	}

	@Override
	public float yaw() {
		return inWorld() ? player().getYRot() : 0;
	}

	@Override
	public float pitch() {
		return inWorld() ? player().getXRot() : 0;
	}

	@Override
	public String dimension() {
		return inWorld() ? level().dimension().identifier().toString() : "";
	}

	@Override
	public String biome(int x, int y, int z) {
		if (!isLoaded(x, z)) {
			return "";
		}
		return level().getBiome(this.place.set(x, y, z)).unwrapKey().map(key -> key.identifier().toString()).orElse("");
	}

	@Override
	public long dayTime() {
		return inWorld() ? level().getOverworldClockTime() % 24000L : 0;
	}

	@Override
	public boolean isRaining() {
		return inWorld() && level().isRaining();
	}

	@Override
	public boolean isLoaded(int x, int z) {
		return inWorld() && level().hasChunk(SectionPos.blockToSectionCoord(x), SectionPos.blockToSectionCoord(z));
	}

	@Override
	public int surfaceY(int x, int z) {
		return isLoaded(x, z) ? level().getHeight(Heightmap.Types.WORLD_SURFACE, x, z) - 1 : NO_HEIGHT;
	}

	@Override
	public String blockName(int x, int y, int z) {
		if (!isLoaded(x, z)) {
			return "minecraft:air";
		}
		return net.minecraft.core.registries.BuiltInRegistries.BLOCK.getKey(level().getBlockState(this.place.set(x, y, z)).getBlock()).toString();
	}

	@Override
	public int lightLevel(int x, int y, int z) {
		if (!isLoaded(x, z)) {
			return 0;
		}
		this.place.set(x, y, z);
		return Math.min(MOST_LIGHT, Math.max(level().getBrightness(LightLayer.SKY, this.place), level().getBrightness(LightLayer.BLOCK, this.place)));
	}

	@Override
	public int mapColor(int x, int z) {
		int[] colour = new int[1];
		readMap(x, z, 1, 1, 1, colour);
		return colour[0];
	}

	@Override
	public void readMap(int fromX, int fromZ, int width, int height, int step, int[] colors) {
		if (width <= 0 || height <= 0 || step <= 0 || (long) width * height > MOST_MAP_PIXELS || colors.length < width * height) {
			throw new IllegalArgumentException("A map of " + width + " by " + height + " doesn't fit in " + colors.length + " colours, or is too big");
		}
		ClientLevel level = level();
		for (int row = 0; row < height; row++) {
			int z = fromZ + row * step;
			ChunkAccess chunk = null;
			int chunkX = Integer.MIN_VALUE;
			for (int column = 0; column < width; column++) {
				int x = fromX + column * step;
				if (SectionPos.blockToSectionCoord(x) != chunkX) {
					chunkX = SectionPos.blockToSectionCoord(x);
					chunk = level == null || !level.hasChunk(chunkX, SectionPos.blockToSectionCoord(z)) ? null : level.getChunk(chunkX, SectionPos.blockToSectionCoord(z));
				}
				colors[row * width + column] = chunk == null ? NOT_LOADED : mapPixel(level, chunk, x, z);
			}
		}
	}

	/** The way the game's own maps do it: water darkens with depth, and land is lighter where it rises to the north and darker where it falls. */
	private int mapPixel(ClientLevel level, ChunkAccess chunk, int x, int z) {
		int surface = chunk.getHeight(Heightmap.Types.WORLD_SURFACE, x & CHUNK_MASK, z & CHUNK_MASK);
		BlockState state = chunk.getBlockState(this.place.set(x, surface, z));
		MapColor colour = state.getMapColor(level, this.place);
		if (colour == MapColor.NONE) {
			return NOT_LOADED;
		}
		MapColor.Brightness brightness = MapColor.Brightness.NORMAL;
		if (colour == MapColor.WATER) {
			int depth = 0;
			int below = surface;
			while (depth < 10 && below > level.getMinY() && !chunk.getFluidState(this.place.set(x, below, z)).isEmpty()) {
				below--;
				depth++;
			}
			brightness = depth < 3 ? MapColor.Brightness.HIGH : depth < 6 ? MapColor.Brightness.NORMAL : MapColor.Brightness.LOW;
		} else if (isLoaded(x, z - 1)) {
			int north = level.getHeight(Heightmap.Types.WORLD_SURFACE, x, z - 1) - 1;
			brightness = surface > north ? MapColor.Brightness.HIGH : surface < north ? MapColor.Brightness.LOW : MapColor.Brightness.NORMAL;
		}
		return colour.calculateARGBColor(brightness);
	}
}
