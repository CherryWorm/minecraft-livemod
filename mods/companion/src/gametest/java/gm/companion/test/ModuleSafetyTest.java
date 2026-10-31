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

/**
 * Proves the companion's safety rules on a real client. broker/tests/m7_test.py pushes modules from the
 * server, one at a time. Lines starting [M7] are read by that script.
 */
public final class ModuleSafetyTest implements FabricClientGameTest {
	private static final Logger LOGGER = LoggerFactory.getLogger("CompanionTest");
	private static final int TICKS_PER_MINUTE = 20 * 60;

	@Override
	public void runTest(ClientGameTestContext context) {
		if (!"safety".equals(System.getenv("CLIENT_TEST"))) {
			return;
		}
		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25566");
		ModuleHost host = Companion.host();

		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
		context.waitFor(client -> client.level != null && client.player != null, 5 * TICKS_PER_MINUTE);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);
		LOGGER.info("[M7] joined");

		// The script sends these in order: unsigned, then signed but forbidden, then good.
		context.waitFor(client -> host.refused() >= 1, 3 * TICKS_PER_MINUTE);
		LOGGER.info("[M7] refused unsigned refused={} active={}", host.refused(), host.isActive("m7_unsigned"));

		context.waitFor(client -> host.refused() >= 2, 3 * TICKS_PER_MINUTE);
		LOGGER.info("[M7] refused forbidden refused={} active={}", host.refused(), host.isActive("m7_forbidden"));

		context.waitFor(client -> host.isActive("m7_good"), 3 * TICKS_PER_MINUTE);
		context.waitTicks(40);
		context.takeScreenshot("m7_good_module");
		LOGGER.info("[M7] signed module active");

		context.runOnClient(client -> host.setTurnedOff(true));
		context.waitTicks(10);
		LOGGER.info("[M7] after turning off active={}", host.isActive("m7_good"));
		context.waitTicks(40);
		context.takeScreenshot("m7_turned_off");
		context.runOnClient(client -> host.setTurnedOff(false));

		context.runOnClient(client -> client.disconnect(new TitleScreen(), false));
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
		LOGGER.info("[M7] finished");
	}
}
