package gm.conduit;

import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Test hook that crashes the server from inside its tick loop if a marker file exists. It's how the
 * broker's tests prove that rollback works and that players are held through an in-game crash.
 */
final class Chaos {
	private static final Path MARKER = Path.of("config", "conduit", "chaos_crash_after_ticks");

	private Chaos() {}

	static void register() {
		if (!Files.exists(MARKER)) {
			return;
		}
		int[] remaining = {readTicks()};
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			if (remaining[0]-- == 0) {
				throw new IllegalStateException("Chaos test: deliberate crash");
			}
		});
	}

	private static int readTicks() {
		try {
			return Integer.parseInt(Files.readString(MARKER).trim());
		} catch (Exception error) {
			return 100;
		}
	}
}
