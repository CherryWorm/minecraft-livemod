package gm.companion.api;

/**
 * What a module can see of the player and the land around them. It's only for looking, and only what this player's game has been told
 * already, so it can't reveal anything that isn't loaded. Until they're in the world, {@link #inWorld} is false and the rest says nothing useful.
 */
public interface WorldView {
	/** The colour a place has when it isn't loaded, which is fully see-through. */
	int NOT_LOADED = 0;

	/** Height this low means a column isn't loaded. */
	int NO_HEIGHT = Integer.MIN_VALUE;

	boolean inWorld();

	double playerX();

	double playerY();

	double playerZ();

	/** Which way they're facing, in degrees: 0 is south, 90 is west, 180 is north and -90 is east. */
	float yaw();

	/** How far up or down they're looking, in degrees, from -90 for straight up to 90 for straight down. */
	float pitch();

	/** The dimension they're in, like "minecraft:overworld". */
	String dimension();

	/** The biome at a place, like "minecraft:plains", or an empty string if it isn't loaded. One of this world's has a name that means nothing. */
	String biome(int x, int y, int z);

	/** The time of day, from 0 at sunrise to 24000, which is a whole day. */
	long dayTime();

	boolean isRaining();

	/** Whether the land at this place has reached this player. */
	boolean isLoaded(int x, int z);

	/** The height of the highest block in a column, or {@link #NO_HEIGHT} if it isn't loaded. Leaves and water count. */
	int surfaceY(int x, int z);

	/** The name of the block at a place, like "minecraft:stone", or "minecraft:air" if it isn't loaded. A block of this world's shows up as whichever of vanilla's stands in for it. */
	String blockName(int x, int y, int z);

	/** How light it is at a place, from 0 to 15, whichever of the sky or a block gives more. */
	int lightLevel(int x, int y, int z);

	/** What a map shows for this column, as 0xAARRGGBB, shaded by how the land slopes the way the game's own maps are, or {@link #NOT_LOADED}. */
	int mapColor(int x, int z);

	/**
	 * What a map shows for a whole area at once, row by row into colors, starting at the north west corner and moving {@code step} blocks each
	 * pixel. This is far quicker than asking one column at a time. It's still work, so do it every so often from a tick, not every frame.
	 */
	void readMap(int fromX, int fromZ, int width, int height, int step, int[] colors);
}
