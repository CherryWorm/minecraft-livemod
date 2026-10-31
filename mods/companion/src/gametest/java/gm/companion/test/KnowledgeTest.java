package gm.companion.test;

import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.inventory.BookViewScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Plays the discovery system the way a player would. broker/tests/m8_test.py sends instructions as chat
 * starting "M8 ", and reads the lines starting [M8] from the log. Real clicks, real crafting grid, real server.
 */
public final class KnowledgeTest implements FabricClientGameTest {
	private static final Logger LOGGER = LoggerFactory.getLogger("CompanionTest");
	private static final int TICKS_PER_MINUTE = 20 * 60;
	private static final String PREFIX = "M8 ";
	private static final int RESULT_SLOT = 0;
	private static final int GRID_A = 1;
	private static final int GRID_B = 2;
	private static final int FIRST_HOTBAR_SLOT = 36;
	private static final int LEFT_BUTTON = 0;
	private static final int RIGHT_BUTTON = 1;

	@Override
	public void runTest(ClientGameTestContext context) {
		if (!"knowledge".equals(System.getenv("CLIENT_TEST"))) {
			return;
		}
		ConcurrentLinkedQueue<String> requests = new ConcurrentLinkedQueue<>();
		ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
			String text = message.getString();
			if (text.startsWith(PREFIX)) {
				requests.add(text.substring(PREFIX.length()));
			} else if (!overlay) {
				LOGGER.info("[M8] chat: {}", text);
			}
		});

		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25565");
		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
		context.waitFor(client -> client.level != null && client.player != null, 5 * TICKS_PER_MINUTE);
		String playerName = context.computeOnClient(client -> client.player.getName().getString());
		LOGGER.info("[M8] joined as {}", playerName);
		context.waitFor(client -> client.gui.screen() == null, 2 * TICKS_PER_MINUTE);

		while (true) {
			context.waitFor(client -> !requests.isEmpty(), 5 * TICKS_PER_MINUTE);
			String request = requests.poll();
			if ("done".equals(request)) {
				break;
			}
			act(context, request);
			LOGGER.info("[M8] finished {}", request);
		}

		context.runOnClient(client -> client.disconnect(new TitleScreen(), false));
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
	}

	private void act(ClientGameTestContext context, String request) {
		String[] words = request.split(" ");
		switch (words[0]) {
			case "craft" -> craft(context);
			case "use" -> context.runOnClient(client -> client.gameMode.useItem(client.player, InteractionHand.MAIN_HAND));
			case "useblock" -> context.runOnClient(client -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				client.gameMode.useItemOn(client.player, InteractionHand.MAIN_HAND,
						new BlockHitResult(Vec3.atCenterOf(pos), Direction.UP, pos, false));
			});
			case "codex" -> {
				context.runOnClient(client -> client.player.connection.sendCommand("codex"));
				context.waitFor(client -> client.gui.screen() instanceof BookViewScreen, TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m8_codex");
				LOGGER.info("[M8] the codex opened");
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "eat" -> context.getInput().holdKeyFor(options -> options.keyUse, 40);
			case "light" -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				int light = context.computeOnClient(client -> client.level.getBrightness(LightLayer.BLOCK, pos));
				LOGGER.info("[M8] block light: {}", light);
			}
			case "shot" -> {
				context.waitTicks(40);
				context.takeScreenshot("m8_" + words[1]);
			}
			default -> LOGGER.warn("[M8] unknown request {}", request);
		}
		context.waitTicks(10);
	}

	/** Puts one of the held stack into each of two grid squares, reads the result, and takes them back out. */
	private void craft(ClientGameTestContext context) {
		click(context, FIRST_HOTBAR_SLOT, LEFT_BUTTON);
		click(context, GRID_A, RIGHT_BUTTON);
		click(context, GRID_B, RIGHT_BUTTON);
		click(context, FIRST_HOTBAR_SLOT, LEFT_BUTTON);
		context.waitTicks(10);
		String result = context.computeOnClient(client -> client.player.inventoryMenu.getSlot(RESULT_SLOT).getItem().getItem().toString());
		LOGGER.info("[M8] crafting result: {}", result);
		for (int slot : new int[] {GRID_A, GRID_B}) {
			click(context, slot, LEFT_BUTTON);
			click(context, FIRST_HOTBAR_SLOT, LEFT_BUTTON);
		}
	}

	private void click(ClientGameTestContext context, int slot, int button) {
		context.runOnClient(client -> client.gameMode.handleContainerInput(
				client.player.inventoryMenu.containerId, slot, button, ContainerInput.PICKUP, client.player));
		context.waitTicks(2);
	}
}
