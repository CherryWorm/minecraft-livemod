package gm.conduit.api;

import gm.conduit.mobs.SlotMob;
import net.minecraft.world.damagesource.DamageSource;

/** Extra behaviour for a slot mob, for anything its definition can't express. Runs on the server. */
public interface MobBehavior {
	default void tick(SlotMob mob) {}

	default void hurt(SlotMob mob, DamageSource source) {}
}
