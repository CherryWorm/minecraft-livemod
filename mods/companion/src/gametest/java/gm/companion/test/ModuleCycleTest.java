package gm.companion.test;

import gm.companion.Companion;
import gm.companion.ModuleHost;
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.management.ManagementFactory;

/**
 * Connects a real client to a real server through the proxy, then watches modules being pushed, swapped
 * and removed. spikes/s4_modules.sh drives the server side. Lines starting [S4] are read by that script.
 */
public final class ModuleCycleTest implements FabricClientGameTest {
	private static final Logger LOGGER = LoggerFactory.getLogger("CompanionTest");
	private static final int TICKS_PER_MINUTE = 20 * 60;
	private static final String MODULE = "s4";

	@Override
	public void runTest(ClientGameTestContext context) {
		if (!"modules".equals(System.getenv("CLIENT_TEST"))) {
			return;
		}
		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25565");
		int cycles = Integer.parseInt(System.getenv().getOrDefault("S4_CYCLES", "100"));
		ModuleHost host = Companion.host();

		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
		context.waitFor(client -> client.level != null && client.player != null, 5 * TICKS_PER_MINUTE);
		String playerName = context.computeOnClient(client -> client.player.getName().getString());
		LOGGER.info("[S4] joined as {}", playerName);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);
		context.waitTicks(60);
		context.takeScreenshot("s4_joined");

		context.waitFor(client -> host.isActive(MODULE), 2 * TICKS_PER_MINUTE);
		context.waitTicks(20);
		context.takeScreenshot("s4_module_active");
		LOGGER.info("[S4] module visible, ready to cycle");

		logMemory(0);
		for (int checkpoint = 10; checkpoint <= cycles; checkpoint += 10) {
			int target = checkpoint;
			context.waitFor(client -> host.completedUnloads() >= target, 5 * TICKS_PER_MINUTE);
			logMemory(checkpoint);
		}

		context.waitFor(client -> !host.isActive(MODULE) && host.completedUnloads() >= cycles, 2 * TICKS_PER_MINUTE);
		context.waitTicks(20);
		context.takeScreenshot("s4_module_gone");
		logMemory(cycles);
		LOGGER.info("[S4] finished: unloads={} disabled_for_errors={}", host.completedUnloads(), host.disabledForErrors());

		// The test framework requires a test to end on the title screen.
		context.runOnClient(client -> client.disconnect(new TitleScreen(), false));
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
	}

	private static void logMemory(int cycle) {
		System.gc();
		System.gc();
		var classes = ManagementFactory.getClassLoadingMXBean();
		long heapMb = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed() / (1024 * 1024);
		LOGGER.info("[S4] memory cycle={} heap_mb={} classes_loaded={} classes_unloaded={}",
				cycle, heapMb, classes.getLoadedClassCount(), classes.getUnloadedClassCount());
	}
}
