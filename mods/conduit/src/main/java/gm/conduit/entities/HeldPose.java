package gm.conduit.entities;

import de.tomalbrc.bil.api.Animator;
import de.tomalbrc.bil.core.model.Animation;
import net.minecraft.util.Mth;

/**
 * One moment of an animation, held so that a test client can photograph exactly that moment. A paused animation shows only the resting
 * pose, so this one keeps playing and gets put back at the same frame every tick.
 */
final class HeldPose {
	private static final int ABOVE_EVERYTHING = 100;

	private String name;
	private int frame;

	boolean start(Animator animator, Animation animation, String name, float fraction) {
		if (animator == null || animation == null) {
			return false;
		}
		if (this.name != null) {
			animator.stopAnimation(this.name);
		}
		this.name = name;
		this.frame = Mth.clamp((int) (fraction * animation.frames().length), 0, animation.frames().length - 1);
		tick(animator);
		return true;
	}

	/** Whether there's a pose being held, because nothing else plays while there is. */
	boolean tick(Animator animator) {
		if (this.name == null) {
			return false;
		}
		animator.playAnimation(this.name, ABOVE_EVERYTHING);
		animator.setAnimationFrame(this.name, this.frame);
		return true;
	}
}
