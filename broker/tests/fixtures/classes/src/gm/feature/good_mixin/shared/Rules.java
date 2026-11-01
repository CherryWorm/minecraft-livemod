package gm.feature.good_mixin.shared;

public final class Rules {
	public static float glide = 0.99F;

	private Rules() {}

	public static float glide(float friction) {
		return Math.max(friction, glide);
	}
}
