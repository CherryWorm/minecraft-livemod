package gm.companion.test;

import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.client.renderer.LevelTargetBundle;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Display;
import net.minecraft.world.entity.Entity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * The broker's eyes. Joins a server through the proxy, then takes a screenshot whenever the server sends
 * "SCENE shot name", until it sends "SCENE done". Lines starting [SCENE] are read by broker/gates/client.py.
 */
public final class SceneTest implements FabricClientGameTest {
	private static final Logger LOGGER = LoggerFactory.getLogger("CompanionTest");
	private static final int TICKS_PER_MINUTE = 20 * 60;
	private static final String PREFIX = "SCENE ";

	@Override
	public void runTest(ClientGameTestContext context) {
		if (!"scene".equals(System.getenv("CLIENT_TEST"))) {
			return;
		}
		ConcurrentLinkedQueue<String> requests = new ConcurrentLinkedQueue<>();
		ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
			String text = message.getString();
			if (text.startsWith(PREFIX)) {
				requests.add(text.substring(PREFIX.length()));
			}
		});

		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25566");
		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
		context.waitFor(client -> client.level != null && client.player != null, 5 * TICKS_PER_MINUTE);
		String playerName = context.computeOnClient(client -> client.player.getName().getString());
		LOGGER.info("[SCENE] joined as {}", playerName);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);

		while (true) {
			context.waitFor(client -> !requests.isEmpty(), 5 * TICKS_PER_MINUTE);
			String request = requests.poll();
			if ("done".equals(request)) {
				break;
			}
			if ("entities".equals(request)) {
				String seen = context.computeOnClient(SceneTest::entitiesSeen);
				LOGGER.info("[SCENE] entities {}", seen);
			}
			if (request.startsWith("mine ")) {
				context.getInput().holdKeyFor(options -> options.keyAttack, Integer.parseInt(request.substring(5)));
				LOGGER.info("[SCENE] mined");
			}
			if (request.startsWith("effect ")) {
				Identifier effect = Identifier.parse(request.substring(7));
				boolean works = context.computeOnClient(client -> client.getShaderManager().getPostChain(effect, LevelTargetBundle.MAIN_TARGETS) != null);
				LOGGER.info("[SCENE] effect {} {}", effect, works ? "works" : "failed");
			}
			if (request.startsWith("shot ")) {
				String name = request.substring(5);
				// The agent is judging the content, so nothing should cover it, unless a HUD is what's being judged.
				boolean showHud = name.startsWith("hud");
				context.runOnClient(client -> {
					if (client.gui.hud.isHidden() == showHud) {
						client.gui.hud.toggle();
					}
					client.gui.toastManager().clear();
				});
				// A frame of a filmed animation is held still and comes in a long series, so a moment to settle is enough.
				context.waitTicks(name.startsWith("frame") ? 6 : 40);
				context.takeScreenshot("scene_" + name);
				LOGGER.info("[SCENE] took {}", name);
			}
		}

		context.runOnClient(client -> client.disconnect(new TitleScreen(), false));
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
	}

	/** What the client has really been told about, because an entity that doesn't show could have failed at any step. */
	private static String entitiesSeen(Minecraft client) {
		Map<String, Integer> counts = new TreeMap<>();
		String display = "no block displays";
		for (Entity entity : client.level.entitiesForRendering()) {
			counts.merge(entity.getType().toShortString(), 1, Integer::sum);
			if (entity instanceof Display.BlockDisplay block) {
				display = block.position() + " " + block.getBlockState() + " rendered as " + (block.renderState() == null ? "nothing yet" : block.renderState().transformation());
			}
		}
		return counts + " " + display;
	}
}
