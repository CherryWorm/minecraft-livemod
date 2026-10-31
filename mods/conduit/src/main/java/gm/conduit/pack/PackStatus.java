package gm.conduit.pack;

import net.minecraft.network.protocol.common.ServerboundResourcePackPacket;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Records how long each player's client takes to apply a pack, which is how long their game freezes. */
public final class PackStatus {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Map<String, Long> STARTED = new ConcurrentHashMap<>();

	private PackStatus() {}

	public static void record(String player, ServerboundResourcePackPacket.Action action) {
		switch (action) {
			case ACCEPTED -> {
				STARTED.put(player, System.nanoTime());
				LOGGER.info("pack accepted by {}", player);
			}
			case DOWNLOADED -> LOGGER.info("pack downloaded by {} after {} ms", player, elapsed(player));
			case SUCCESSFULLY_LOADED -> LOGGER.info("pack loaded by {} after {} ms", player, elapsed(player));
			default -> LOGGER.warn("pack problem for {}: {}", player, action);
		}
	}

	private static long elapsed(String player) {
		Long start = STARTED.get(player);
		return start == null ? -1 : (System.nanoTime() - start) / 1_000_000;
	}
}
