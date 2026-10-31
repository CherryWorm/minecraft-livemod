package gm.conduit.api;

import gm.conduit.mobs.SlotMob;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.LivingEntity;

/** Extra behaviour for a slot mob, for anything its definition can't express. Runs on the server. */
public interface MobBehavior {
	default void tick(SlotMob mob) {}

	default void hurt(SlotMob mob, DamageSource source) {}

	/** Carries out one of the fight moves listed in the mob's mind. Its mind chooses which and when, and this is what it does. */
	default void move(SlotMob mob, String name, LivingEntity target) {}
}
