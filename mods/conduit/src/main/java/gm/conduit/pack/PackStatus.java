package gm.conduit.pack;

import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.network.protocol.common.ServerboundResourcePackPacket;
import net.minecraft.server.level.ServerPlayer;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Records how long each player's client takes to apply a pack, which is how long their game freezes,
 * and keeps them from being hurt until it's done, since they can't react during that time.
 */
public final class PackStatus {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final long MAX_PROTECTED_NANOS = 30_000_000_000L;
	private static final Map<String, Long> STARTED = new ConcurrentHashMap<>();
	private static final Map<ServerPlayer, Long> PROTECTED = new ConcurrentHashMap<>();

	private PackStatus() {}

	public static void register() {
		// A client that never reports back mustn't stay invulnerable.
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			long now = System.nanoTime();
			PROTECTED.entrySet().removeIf(entry -> {
				if (entry.getKey().isRemoved() || now - entry.getValue() > MAX_PROTECTED_NANOS) {
					entry.getKey().setInvulnerable(false);
					return true;
				}
				return false;
			});
		});
	}

	public static void record(String name, @Nullable ServerPlayer player, ServerboundResourcePackPacket.Action action) {
		switch (action) {
			case ACCEPTED -> {
				STARTED.put(name, System.nanoTime());
				LOGGER.info("pack accepted by {}", name);
				if (player != null && !player.isInvulnerable()) {
					player.setInvulnerable(true);
					PROTECTED.put(player, System.nanoTime());
				}
			}
			case DOWNLOADED -> LOGGER.info("pack downloaded by {} after {} ms", name, elapsed(name));
			case SUCCESSFULLY_LOADED -> {
				LOGGER.info("pack loaded by {} after {} ms", name, elapsed(name));
				release(player);
			}
			default -> {
				LOGGER.warn("pack problem for {}: {}", name, action);
				release(player);
			}
		}
	}

	private static void release(@Nullable ServerPlayer player) {
		if (player != null && PROTECTED.remove(player) != null) {
			player.setInvulnerable(false);
		}
	}

	private static long elapsed(String name) {
		Long start = STARTED.get(name);
		return start == null ? -1 : (System.nanoTime() - start) / 1_000_000;
	}
}
