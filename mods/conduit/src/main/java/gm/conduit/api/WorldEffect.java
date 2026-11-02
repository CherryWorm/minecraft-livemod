package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.state.BlockState;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Something drawn at a place in the world for a while, with no client module. Make one with box, sheet, beam, billboard, burst or blocks, add
 * to it with {@link #and}, say how it looks, and show it with context.showEffect. For example
 * {@code WorldEffect.beam(x, 64, z, x, 200, z, 0.5F).color(0xC0FF8800).glowing().seconds(10).fade(2)}.
 */
public final class WorldEffect {
	/** How much can be drawn at once from one call, so a list of blocks or shapes has to fit in this. */
	public static final int MOST_PARTS = 4096;
	// The numbers the companion's WorldDrawing knows them by.
	public static final int BOX = 0;
	public static final int SHEET = 1;
	public static final int BEAM = 2;
	public static final int BILLBOARD = 3;
	public static final int BLOCK = 4;
	public static final int BURST = 5;
	/** The most specks one burst can have. */
	public static final int MOST_SPECKS = 512;
	private static final float DEFAULT_SECONDS = 5;
	private static final double DEFAULT_RANGE = 64;
	private static final double DEFAULT_GRAVITY = 6;
	private static final int GRAVITY_PLACE = 4;
	private static final int MOST_SEED = 1 << 24;

	private final List<Part> parts = new ArrayList<>();
	private int color = 0xFFFFFFFF;
	private String image = "";
	private String shader = "";
	private boolean glowing;
	private boolean throughWalls;
	private float seconds = DEFAULT_SECONDS;
	private float fade;
	private float moveX;
	private float moveY;
	private float moveZ;
	private String key = "";
	private double range = DEFAULT_RANGE;

	private WorldEffect() {}

	/** One thing in an effect, as the host reads it. */
	public record Part(int kind, double[] places, float width, float height, BlockState block) {}

	/** A box between two corners, with the whole image on each face. */
	public static WorldEffect box(double x1, double y1, double z1, double x2, double y2, double z2) {
		return new WorldEffect().add(BOX, new double[] {x1, y1, z1, x2, y2, z2, 0, 0, 0}, 0, 0, null);
	}

	/** A flat surface at any angle, from one corner along two edges, seen from both sides. */
	public static WorldEffect sheet(double x, double y, double z, double edgeX1, double edgeY1, double edgeZ1, double edgeX2, double edgeY2, double edgeZ2) {
		return new WorldEffect().add(SHEET, new double[] {x, y, z, edgeX1, edgeY1, edgeZ1, edgeX2, edgeY2, edgeZ2}, 0, 0, null);
	}

	/** A line between two points that always turns its face to the camera, this wide in blocks. */
	public static WorldEffect beam(double x1, double y1, double z1, double x2, double y2, double z2, float width) {
		return new WorldEffect().add(BEAM, new double[] {x1, y1, z1, x2, y2, z2, 0, 0, 0}, width, 0, null);
	}

	/** A picture centred on a point that always faces the camera, this big in blocks. */
	public static WorldEffect billboard(double x, double y, double z, float width, float height) {
		return new WorldEffect().add(BILLBOARD, new double[] {x, y, z, 0, 0, 0, 0, 0, 0}, width, height, null);
	}

	/**
	 * Particles of your own: this many specks flying out from a point at up to this many blocks a second, each this big in blocks and facing the camera,
	 * then falling. Give it a color or an image, and {@link #seconds} and {@link #fade}, which is how particles of the game's own behave, so a second or two
	 * is usual. Everyone sees the same burst, each worked out on their own computer, so even a lot of them cost the server nothing.
	 */
	public static WorldEffect burst(double x, double y, double z, int count, float speed, float size) {
		return new WorldEffect().add(BURST, new double[] {x, y, z, speed, DEFAULT_GRAVITY, ThreadLocalRandom.current().nextInt(MOST_SEED), 0, 0, 0}, size, Math.clamp(count, 1, MOST_SPECKS), null);
	}

	/** How fast a burst's specks fall, in blocks a second every second, which is 6 unless you say. 0 is for something that floats, and below 0 rises. */
	public WorldEffect gravity(double blocks) {
		for (Part part : this.parts) {
			if (part.kind() == BURST) {
				part.places()[GRAVITY_PLACE] = blocks;
			}
		}
		return this;
	}

	/** Nothing yet, for see-through copies of blocks to be added with {@link #block}, which is how to show the layout of something to be built. */
	public static WorldEffect blocks() {
		return new WorldEffect();
	}

	/** Adds a see-through copy of a block, vanilla's or this world's. Color tints it, and an image or a shader is ignored for these. */
	public WorldEffect block(BlockPos pos, BlockState state) {
		return add(BLOCK, new double[] {pos.getX(), pos.getY(), pos.getZ(), 0, 0, 0, 0, 0, 0}, 0, 0, state);
	}

	/** Everything in another effect as well, drawn with this one's look. */
	public WorldEffect and(WorldEffect other) {
		this.parts.addAll(other.parts);
		return this;
	}

	private WorldEffect add(int kind, double[] places, float width, float height, BlockState block) {
		this.parts.add(new Part(kind, places, width, height, block));
		return this;
	}

	/** What it's tinted, as 0xAARRGGBB, so 0x80FF0000 is half see-through red. */
	public WorldEffect color(int argb) {
		this.color = argb;
		return this;
	}

	/** One of this feature's "world_images", or "other_feature/name". */
	public WorldEffect image(String name) {
		this.image = name;
		return this;
	}

	/** One of this feature's "world_shaders", or "other_feature/name". */
	public WorldEffect shader(String name) {
		this.shader = name;
		return this;
	}

	/** Adds to what's behind it rather than covering it, and takes no fog, so it shows from far away. Best at night. */
	public WorldEffect glowing() {
		this.glowing = true;
		return this;
	}

	/** Shows through whatever's in front of it. */
	public WorldEffect throughWalls() {
		this.throughWalls = true;
		return this;
	}

	/** How long it stays, which is 5 seconds unless you say. With 0, it stays until clearEffect takes it away, which needs a {@link #key}. */
	public WorldEffect seconds(float seconds) {
		this.seconds = seconds;
		return this;
	}

	/** How long before it runs out it starts to fade. */
	public WorldEffect fade(float seconds) {
		this.fade = seconds;
		return this;
	}

	/** How far it travels each second, in blocks, which players' computers work out smoothly by themselves. */
	public WorldEffect moving(float x, float y, float z) {
		this.moveX = x;
		this.moveY = y;
		this.moveZ = z;
		return this;
	}

	/** Its name, for replacing it by showing another with the same key, or taking it away early with clearEffect. */
	public WorldEffect key(String key) {
		this.key = key;
		return this;
	}

	/** How close to its first point players have to be to get it, which is 64 blocks unless you say. Something in the sky wants more. */
	public WorldEffect range(double blocks) {
		this.range = blocks;
		return this;
	}

	public List<Part> parts() {
		return this.parts;
	}

	public int color() {
		return this.color;
	}

	public String image() {
		return this.image;
	}

	public String shader() {
		return this.shader;
	}

	public boolean isGlowing() {
		return this.glowing;
	}

	public boolean isThroughWalls() {
		return this.throughWalls;
	}

	public float seconds() {
		return this.seconds;
	}

	public float fade() {
		return this.fade;
	}

	public float moveX() {
		return this.moveX;
	}

	public float moveY() {
		return this.moveY;
	}

	public float moveZ() {
		return this.moveZ;
	}

	public String key() {
		return this.key;
	}

	public double range() {
		return this.range;
	}
}
