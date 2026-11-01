package gm.conduit.bridge;

import net.fabricmc.fabric.api.entity.event.v1.ServerEntityLevelChangeEvents;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.phys.AABB;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/** Whether a player can safely take a few seconds of frozen game, as a pack reload or restart causes. */
public final class SafeMoment {
	private static final double HOSTILE_RANGE = 16.0;
	/** The game doesn't hear when a client has finished loading a dimension it's just arrived in, so this is about how long that takes. */
	private static final int CROSSING_TICKS = 100;
	private static final Map<UUID, Integer> LAST_CROSSED = new HashMap<>();

	private SafeMoment() {}

	public static void register() {
		ServerEntityLevelChangeEvents.AFTER_PLAYER_CHANGE_LEVEL.register((player, origin, destination) ->
				LAST_CROSSED.put(player.getUUID(), destination.getServer().getTickCount()));
	}

	public static boolean isSafe(ServerPlayer player) {
		// Partway between dimensions, they're still looking at a loading screen. A reload on top of that takes twice as long to get through, and when it ends they've arrived somewhere they haven't seen.
		Integer crossed = LAST_CROSSED.get(player.getUUID());
		if (player.isChangingDimension() || !player.connection.hasClientLoaded()
				|| (crossed != null && player.level().getServer().getTickCount() - crossed < CROSSING_TICKS)) {
			return false;
		}
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
