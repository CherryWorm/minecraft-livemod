package gm.conduit.api;

import net.minecraft.world.entity.LivingEntity;

/** What a status effect from a feature's "effects" does. Runs on the server. A method left out does nothing. */
public interface EffectBehavior {
	/** Runs every tick for each thing that has this, so keep it small. The level starts at 0, the same as the game's own amplifier. */
	default void tick(LivingEntity entity, int level) {}

	/** Something has just got this, or got a stronger one, or the same one again. */
	default void started(LivingEntity entity, int level) {}

	/** Something no longer has this, because it ran out or was taken away. Dying counts, and so does milk. */
	default void ended(LivingEntity entity) {}
}
