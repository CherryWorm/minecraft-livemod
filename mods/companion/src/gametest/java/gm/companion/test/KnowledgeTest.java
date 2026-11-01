package gm.companion.test;

import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.mixin.AbstractContainerScreenAccessor;
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.TestInput;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.BookViewScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.numbers.BlankFormat;
import net.minecraft.resources.Identifier;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.scores.DisplaySlot;
import net.minecraft.world.scores.Objective;
import net.minecraft.world.scores.Scoreboard;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Comparator;
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

		// The game gives up on a sound the pack doesn't have before it gets this far, so this also proves the pack has it.
		context.runOnClient(client -> client.getSoundManager().addListener((sound, events, range) -> {
			if (sound.getIdentifier().getNamespace().equals("gm")) {
				LOGGER.info("[M8] sound: {}", sound.getIdentifier());
			}
		}));
		connect(context);
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
			case "eat" -> {
				boolean food = context.computeOnClient(client -> client.player.getMainHandItem().has(DataComponents.CONSUMABLE));
				LOGGER.info("[M8] the client sees it as food: {}", food);
				context.getInput().holdKeyFor(options -> options.keyUse, 40);
			}
			case "light" -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				int light = context.computeOnClient(client -> client.level.getBrightness(LightLayer.BLOCK, pos));
				LOGGER.info("[M8] block light: {}", light);
			}
			case "say" -> context.runOnClient(client -> client.player.connection.sendChat(request.substring(4)));
			case "command" -> context.runOnClient(client -> client.player.connection.sendCommand(request.substring(8)));
			case "sidebar" -> {
				context.waitTicks(10);
				String sidebar = context.computeOnClient(client -> sidebar(client.level.getScoreboard()));
				LOGGER.info("[M8] sidebar: {}", sidebar);
			}
			case "rightclick" -> {
				String target = context.computeOnClient(client -> String.valueOf(client.hitResult == null ? null : client.hitResult.getType()));
				LOGGER.info("[M8] using what the crosshair is on, which is a {}", target);
				context.getInput().holdKeyFor(options -> options.keyUse, 2);
			}
			case "mine" -> {
				String target = context.computeOnClient(client -> String.valueOf(client.hitResult == null ? null : client.hitResult.getLocation()));
				LOGGER.info("[M8] mining what the crosshair is on, at {}", target);
				context.getInput().holdKeyFor(options -> options.keyAttack, Integer.parseInt(words[1]));
			}
			case "shot" -> {
				context.waitTicks(40);
				context.takeScreenshot("m8_" + words[1]);
			}
			case "inventory" -> {
				context.getInput().pressKey(options -> options.keyInventory);
				context.waitFor(client -> client.gui.screen() instanceof AbstractContainerScreen<?>, TICKS_PER_MINUTE);
			}
			case "close" -> context.runOnClient(client -> client.gui.setScreen(null));
			case "chat" -> context.runOnClient(client -> client.gui.setScreen(new ChatScreen("", false)));
			case "press" -> context.getInput().pressKey(Integer.parseInt(words[1]));
			case "shiftdrag" -> shiftDrag(context, words);
			case "sneak" -> context.getInput().holdShift();
			case "unsneak" -> context.getInput().releaseShift();
			case "hold" -> context.getInput().holdKeyFor(options -> options.keyUse, Integer.parseInt(words[1]));
			case "click" -> context.runOnClient(client -> client.gameMode.handleContainerInput(client.player.containerMenu.containerId, Integer.parseInt(words[1]),
					words.length > 2 && words[2].equals("right") ? RIGHT_BUTTON : LEFT_BUTTON, words.length > 2 && words[2].equals("shift") ? ContainerInput.QUICK_MOVE : ContainerInput.PICKUP, client.player));
			case "closemenu" -> context.runOnClient(client -> client.player.closeContainer());
			case "menu" -> {
				String shown = context.computeOnClient(client -> {
					StringBuilder slots = new StringBuilder();
					for (int slot = 0; slot < client.player.containerMenu.slots.size() - 36; slot++) {
						ItemStack stack = client.player.containerMenu.getSlot(slot).getItem();
						slots.append(slot).append('=').append(stack.isEmpty() ? "empty" : stack.getCount() + "x" + stack.getItem()).append(' ');
					}
					return slots + "carried=" + client.player.containerMenu.getCarried().getCount();
				});
				LOGGER.info("[M8] menu holds {}", shown);
			}
			case "held" -> {
				String shown = context.computeOnClient(client -> {
					ItemStack stack = client.player.getMainHandItem();
					return stack.getCount() + " tooltip " + stack.getTooltipLines(net.minecraft.world.item.Item.TooltipContext.of(client.level), client.player, net.minecraft.world.item.TooltipFlag.NORMAL).stream().map(line -> line.getString()).toList()
							+ " data " + stack.has(DataComponents.CUSTOM_MODEL_DATA) + " tracker " + stack.has(DataComponents.LODESTONE_TRACKER);
				});
				LOGGER.info("[M8] holding {}", shown);
			}
			case "blockat" -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				String seen = context.computeOnClient(client -> client.level.getBlockState(pos).toString());
				LOGGER.info("[M8] the client sees {}", seen);
			}
			case "oldcompanion" -> rejoinAsOldCompanion(context);
			case "screen" -> {
				String shown = context.computeOnClient(client -> client.gui.screen() == null ? "none" : client.gui.screen().getClass().getSimpleName());
				LOGGER.info("[M8] the screen is {}", shown);
			}
			default -> LOGGER.warn("[M8] unknown request {}", request);
		}
		context.waitTicks(10);
	}

	private static String sidebar(Scoreboard scoreboard) {
		Objective objective = scoreboard.getDisplayObjective(DisplaySlot.SIDEBAR);
		if (objective == null) {
			return "none";
		}
		StringBuilder shown = new StringBuilder(objective.getDisplayName().getString());
		scoreboard.listPlayerScores(objective).stream()
				.sorted(Comparator.comparingInt(entry -> -entry.value()))
				.forEach(entry -> shown.append(" | ").append(entry.ownerName().getString())
						.append(" = ").append(entry.formatValue(objective.numberFormatOrDefault(BlankFormat.INSTANCE)).getString()));
		return shown.toString();
	}

	/** Holds shift and the left button, and moves the real mouse across these slots of the open screen. */
	private void shiftDrag(ClientGameTestContext context, String[] words) {
		TestInput input = context.getInput();
		input.holdShift();
		for (int word = 1; word < words.length; word++) {
			int slot = Integer.parseInt(words[word]);
			double[] pixel = context.computeOnClient(client -> {
				AbstractContainerScreen<?> screen = (AbstractContainerScreen<?>) client.gui.screen();
				AbstractContainerScreenAccessor at = (AbstractContainerScreenAccessor) screen;
				Slot found = screen.getMenu().getSlot(slot);
				double scale = client.getWindow().getGuiScale();
				return new double[] {(at.companion$leftPos() + found.x + 8) * scale, (at.companion$topPos() + found.y + 8) * scale};
			});
			input.setCursorPos(pixel[0], pixel[1]);
			context.waitTicks(2);
			if (word == 1) {
				input.holdMouse(InputConstants.MOUSE_BUTTON_LEFT);
				context.waitTicks(2);
			}
		}
		input.releaseMouse(InputConstants.MOUSE_BUTTON_LEFT);
		input.releaseShift();
	}

	/** Which channels it listens on is all a server can see of a companion, so this looks just like one from before inventory hooks. */
	private void rejoinAsOldCompanion(ClientGameTestContext context) {
		context.runOnClient(client -> {
			ClientPlayNetworking.unregisterGlobalReceiver(Identifier.fromNamespaceAndPath("gm", "inventory_hooks"));
			client.getConnection().getConnection().disconnect(Component.literal("Leaving"));
			client.disconnect(new TitleScreen(), false);
		});
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
		// Long enough for the proxy to notice, or it refuses the same player connecting twice.
		context.waitTicks(60);
		connect(context);
		context.waitFor(client -> client.level != null && client.player != null && client.gui.screen() == null, 5 * TICKS_PER_MINUTE);
	}

	private void connect(ClientGameTestContext context) {
		String address = System.getenv().getOrDefault("LIVINGMOD_SERVER", "localhost:25565");
		context.runOnClient(client -> {
			ServerData data = new ServerData("test", address, ServerData.Type.OTHER);
			data.setResourcePackStatus(ServerData.ServerPackStatus.ENABLED);
			ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(address), data, false, null);
		});
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
