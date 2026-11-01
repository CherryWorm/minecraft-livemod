package gm.conduit.api;

import gm.conduit.entities.SlotVehicle;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.player.Player;

/** Extra behaviour for a vehicle, for anything its definition can't express, such as fuel. Runs on the server. */
public interface VehicleBehavior {
	default void tick(SlotVehicle vehicle) {}

	/**
	 * A player used an item or an empty hand on it, such as to refuel it. Anything but PASS is the end of it, and PASS goes on to them getting in.
	 * It's called once for each hand, so check which one if that matters, and use up the item yourself.
	 */
	default InteractionResult interact(SlotVehicle vehicle, Player player, InteractionHand hand) {
		return InteractionResult.PASS;
	}

	default void boarded(SlotVehicle vehicle, ServerPlayer rider) {}

	default void left(SlotVehicle vehicle, ServerPlayer rider) {}

	default void hurt(SlotVehicle vehicle, DamageSource source) {}
}
