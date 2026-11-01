package gm.conduit.api;

import gm.conduit.mobs.SlotMob;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;

/** Extra behaviour for a slot mob, for anything its definition can't express. Runs on the server. */
public interface MobBehavior {
	default void tick(SlotMob mob) {}

	default void hurt(SlotMob mob, DamageSource source) {}

	/**
	 * A player used an item or an empty hand on it, such as to feed it. Goes ahead of its mind, so anything but PASS is the
	 * end of it, and PASS carries on to its mind if it has one. It's called once for each hand, so check which one if that
	 * matters, and use up the item yourself.
	 */
	default InteractionResult interact(SlotMob mob, Player player, InteractionHand hand) {
		return InteractionResult.PASS;
	}

	/** Carries out one of the fight moves listed in the mob's mind. Its mind chooses which and when, and this is what it does. */
	default void move(SlotMob mob, String name, LivingEntity target) {}
}
