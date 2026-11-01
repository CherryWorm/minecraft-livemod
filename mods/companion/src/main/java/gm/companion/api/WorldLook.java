package gm.companion.api;

/**
 * How something drawn in the world looks. It's fixed once made, so keep one in a field and use it every frame.
 *
 * @param color what it's tinted, as 0xAARRGGBB, so 0x80FF0000 is half see-through red
 * @param image one of this feature's "world_images", or "other_feature/name", or an empty string for a plain colour
 * @param shader one of this feature's "world_shaders", or "other_feature/name", or an empty string for none
 * @param isGlowing adds to what's behind it rather than covering it, and takes no fog, so it shows from far away. Best at night
 * @param isThroughWalls shows through whatever's in front of it, so a player can see it from anywhere
 */
public record WorldLook(int color, String image, String shader, boolean isGlowing, boolean isThroughWalls) {
	public static WorldLook of(int color) {
		return new WorldLook(color, "", "", false, false);
	}

	public WorldLook image(String name) {
		return new WorldLook(this.color, name, this.shader, this.isGlowing, this.isThroughWalls);
	}

	public WorldLook shader(String name) {
		return new WorldLook(this.color, this.image, name, this.isGlowing, this.isThroughWalls);
	}

	public WorldLook color(int argb) {
		return new WorldLook(argb, this.image, this.shader, this.isGlowing, this.isThroughWalls);
	}

	public WorldLook glowing() {
		return new WorldLook(this.color, this.image, this.shader, true, this.isThroughWalls);
	}

	public WorldLook throughWalls() {
		return new WorldLook(this.color, this.image, this.shader, this.isGlowing, true);
	}
}
