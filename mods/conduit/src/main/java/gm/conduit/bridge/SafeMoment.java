package gm.conduit.bridge;

import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.phys.AABB;

/** Whether a player can safely take a few seconds of frozen game, as a pack reload or restart causes. */
public final class SafeMoment {
	private static final double HOSTILE_RANGE = 16.0;

	private SafeMoment() {}

	public static boolean isSafe(ServerPlayer player) {
		if (player.isCreative() || player.isSpectator()) {
			return true;
		}
		if (player.fallDistance > 3.0 || player.isOnFire() || player.isInLava()) {
			return false;
		}
		if (player.isUnderWater() && player.getAirSupply() < player.getMaxAirSupply() / 2) {
			return false;
		}
		AABB nearby = player.getBoundingBox().inflate(HOSTILE_RANGE);
		return player.level().getEntitiesOfClass(Monster.class, nearby).isEmpty();
	}
}
