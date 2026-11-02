package gm.companion.test;

import com.google.gson.Gson;
import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.guide.Guide;
import gm.companion.jei.CompanionJeiPlugin;
import gm.companion.mixin.AbstractContainerScreenAccessor;
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest;
import net.fabricmc.fabric.api.client.gametest.v1.TestInput;
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.CameraType;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Options;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.BookViewScreen;
import net.minecraft.client.gui.screens.options.controls.KeyBindsScreen;
import net.minecraft.client.gui.screens.recipebook.RecipeCollection;
import net.minecraft.client.multiplayer.ClientAdvancements;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.numbers.BlankFormat;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.util.context.ContextMap;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.EnchantmentMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.display.RecipeDisplayEntry;
import net.minecraft.world.item.crafting.display.ShapelessCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.SlotDisplayContext;
import net.minecraft.world.level.LightLayer;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.scores.DisplaySlot;
import net.minecraft.world.scores.Objective;
import net.minecraft.world.scores.Scoreboard;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.function.Function;

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
			// A long time, because a test can have a whole release to wait for between one request and the next.
			context.waitFor(client -> !requests.isEmpty(), 30 * TICKS_PER_MINUTE);
			String request = requests.poll();
			if ("done".equals(request)) {
				break;
			}
			act(context, request);
			LOGGER.info("[M8] finished {}", request);
		}

		context.runOnClient(client -> client.disconnect(new TitleScreen(), false));
		context.waitFor(client -> client.level == null && client.gui.screen() instanceof TitleScreen, TICKS_PER_MINUTE);
		// The next thing the test runner does is reset the game's options, which it can't do for a module's key it never knew.
		context.waitFor(client -> Arrays.stream(client.options.keyMappings).noneMatch(key -> key.getName().startsWith("key.gm.")), TICKS_PER_MINUTE);
	}

	/** What a client has really been told about each part of a model, for a test to compare with what a module asked for. */
	private static String describeParts(net.minecraft.client.Minecraft client, BlockPos pos) {
		var box = new net.minecraft.world.phys.AABB(pos).inflate(0.5);
		StringBuilder parts = new StringBuilder("[");
		var displays = new java.util.ArrayList<>(client.level.getEntitiesOfClass(net.minecraft.world.entity.Display.ItemDisplay.class, box));
		displays.sort(java.util.Comparator.comparingInt(net.minecraft.world.entity.Entity::getId));
		for (var display : displays) {
			var look = display.renderState().transformation().get(1.0F);
			var translation = look.translation();
			var rotation = look.leftRotation();
			var stack = display.getSlot(0).get();
			var brightness = display.getBrightnessOverride();
			var tint = stack.get(DataComponents.DYED_COLOR);
			parts.append(parts.length() > 1 ? "," : "").append(String.format(java.util.Locale.ROOT,
					"{\"x\":%.3f,\"y\":%.3f,\"z\":%.3f,\"scale\":%.3f,\"rotation\":\"%.2f %.2f %.2f %.2f\",\"brightness\":%d,\"tint\":%d}",
					translation.x(), translation.y(), translation.z(), look.scale().x(), rotation.x(), rotation.y(), rotation.z(), rotation.w(),
					brightness == null ? -1 : brightness.block(), tint == null ? -1 : tint.rgb() & 0xFFFFFF));
		}
		return parts.append("]").toString();
	}

	private static String riding(Minecraft client) {
		Entity vehicle = client.player.getVehicle();
		return "%.3f %.3f %.3f yaw %.2f riding %s".formatted(client.player.getX(), client.player.getY(), client.player.getZ(), client.player.getYRot(),
				vehicle == null ? "nothing" : vehicle.getType().toShortString() + " of " + client.player.getRootVehicle().getType().toShortString());
	}

	/** Holds a key down and says where the player was every tick, which shows how smooth a ride really is on the client. */
	private void drive(ClientGameTestContext context, String key, int ticks) {
		Function<Options, KeyMapping> mapping = switch (key) {
			case "forward" -> options -> options.keyUp;
			case "back" -> options -> options.keyDown;
			case "left" -> options -> options.keyLeft;
			case "right" -> options -> options.keyRight;
			case "jump" -> options -> options.keyJump;
			default -> options -> options.keySprint;
		};
		context.getInput().holdKey(mapping);
		for (int i = 0; i < ticks; i++) {
			context.waitTick();
			LOGGER.info("[M8] rode: {}", context.computeOnClient(KnowledgeTest::riding));
		}
		context.getInput().releaseKey(mapping);
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
			case "guide" -> LOGGER.info("[M8] guide: {}", Guide.describe());
			case "guideopen" -> {
				context.runOnClient(client -> client.player.connection.sendCommand("codex"));
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m22_landing");
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "guidekey" -> {
				context.getInput().pressKey(options -> Guide.openKey());
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "guideat" -> {
				context.runOnClient(client -> client.player.connection.sendCommand("codex " + words[1]));
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m22_opened_at");
				context.runOnClient(client -> {
					LOGGER.info("[M8] screen: {}", client.gui.screen().getClass().getSimpleName());
					client.gui.setScreen(null);
				});
			}
			case "guidecategory" -> {
				context.runOnClient(client -> Guide.showCategory(request.substring(request.indexOf(' ') + 1)));
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m22_category_" + words[1]);
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "guideindex" -> {
				context.runOnClient(client -> Guide.showIndex());
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m22_index");
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "guideshow" -> {
				int page = Integer.parseInt(words[1]);
				context.runOnClient(client -> Guide.show(request.substring(request.indexOf(' ', "guideshow ".length()) + 1), page));
				context.waitFor(client -> Guide.isOpen(), TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m22_entry_" + page);
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
			case "where" -> {
				String shown = context.computeOnClient(client -> {
					BlockPos at = client.player.blockPosition();
					return new Gson().toJson(java.util.Map.of("dimension", client.level.dimension().identifier().toString(), "x", at.getX(), "y", at.getY(), "z", at.getZ(),
							"under", client.level.getBlockState(at.below()).getBlock().toString(), "biome", client.level.getBiome(at).getRegisteredName(),
							"ambient", client.level.dimensionType().ambientLight()));
				});
				LOGGER.info("[M8] where: {}", shown);
			}
			case "recipebook" -> logRecipeBook(context);
			case "jei" -> logJei(context, ItemStack.EMPTY);
			case "jeimakes" -> logJei(context, context.computeOnClient(client -> client.player.getMainHandItem().copy()));
			case "standin" -> {
				String item = context.computeOnClient(client -> String.valueOf(client.player.getMainHandItem().getItem()));
				LOGGER.info("[M8] an item from this world is shown as: {}", item);
			}
			case "jeipage" -> {
				context.runOnClient(client -> CompanionJeiPlugin.showPage());
				context.waitTicks(40);
				context.takeScreenshot("m8_jei");
				context.runOnClient(client -> client.gui.setScreen(null));
			}
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
			case "drive" -> drive(context, words[1], Integer.parseInt(words[2]));
			case "camera" -> context.runOnClient(client -> client.options.setCameraType(words[1].equals("third") ? CameraType.THIRD_PERSON_BACK : CameraType.FIRST_PERSON));
			case "riding" -> LOGGER.info("[M8] riding: {}", context.computeOnClient(KnowledgeTest::riding));
			case "shotnow" -> context.takeScreenshot("m8_" + words[1]);
			case "hud" -> context.runOnClient(client -> {
				if (client.gui.hud.isHidden() != words[1].equals("off")) {
					client.gui.hud.toggle();
				}
			});
			case "look" -> context.getInput().lookAt(Float.parseFloat(words[1]), Float.parseFloat(words[2]));
			case "hit" -> {
				for (int i = 0; i < Integer.parseInt(words[1]); i++) {
					context.getInput().pressKey(options -> options.keyAttack);
					context.waitTicks(12);
				}
			}
			case "entities" -> {
				Map<String, Integer> counts = new TreeMap<>();
				context.runOnClient(client -> client.level.entitiesForRendering().forEach(entity -> counts.merge(entity.getType().toShortString(), 1, Integer::sum)));
				LOGGER.info("[M8] entities: {}", counts);
				int chunks = context.computeOnClient(client -> client.options.getEffectiveRenderDistance());
				LOGGER.info("[M8] render distance: {}", chunks);
			}
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
			case "parts" -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				String parts = context.computeOnClient(client -> describeParts(client, pos));
				LOGGER.info("[M8] parts: {}", parts);
			}
			case "barheld" -> {
				String bar = context.computeOnClient(client -> {
					ItemStack stack = client.player.getMainHandItem();
					return "{\"visible\":" + stack.isBarVisible() + ",\"width\":" + stack.getBarWidth() + "}";
				});
				LOGGER.info("[M8] bar: {}", bar);
			}
			case "holdjump" -> context.getInput().holdKeyFor(options -> options.keyJump, Integer.parseInt(words[1]));
			case "holdforward" -> context.getInput().holdKeyFor(options -> options.keyUp, Integer.parseInt(words[1]));
			case "doubletapjump" -> {
				context.getInput().holdKeyFor(options -> options.keyJump, 2);
				context.waitTicks(2);
				context.getInput().holdKeyFor(options -> options.keyJump, 2);
			}
			case "effects" -> {
				String shown = context.computeOnClient(client -> {
					StringBuilder effects = new StringBuilder("[");
					for (var effect : client.player.getActiveEffects()) {
						var kind = effect.getEffect().value();
						if (kind.getDisplayName().getString().startsWith("Api")) {
							effects.append(effects.length() > 1 ? "," : "").append(String.format(java.util.Locale.ROOT, "{\"name\":\"%s\",\"level\":%d,\"ticks\":%d,\"harmful\":%b,\"sprite\":\"%s\"}",
									kind.getDisplayName().getString(), effect.getAmplifier(), effect.getDuration(), kind.getCategory() == net.minecraft.world.effect.MobEffectCategory.HARMFUL, net.minecraft.client.gui.Hud.getMobEffectSprite(effect.getEffect())));
						}
					}
					return effects.append("]").toString();
				});
				LOGGER.info("[M8] effects: {}", shown);
			}
			case "respawn" -> context.runOnClient(client -> {
				client.player.respawn();
				client.gui.setScreen(null);
			});
			case "inwater" -> {
				boolean wet = context.computeOnClient(client -> client.player.isInWater());
				LOGGER.info("[M8] in water: {}", wet);
			}
			case "hotbarclick" -> context.runOnClient(client -> client.gameMode.handleContainerInput(client.player.containerMenu.containerId,
					client.player.containerMenu.slots.size() - 9 + Integer.parseInt(words[1]), LEFT_BUTTON, ContainerInput.PICKUP, client.player));
			case "oldcompanion" -> rejoinWithout(context, "inventory_hooks");
			case "nopanels" -> rejoinWithout(context, "panel");
			case "noworld" -> rejoinWithout(context, "world_show");
			case "noburst" -> rejoinWithout(context, "world_burst");
			// Leaves and comes back, looking the same as ever, because nothing is listening on a channel of this name.
			case "rejoin" -> rejoinWithout(context, "nothing");
			case "nonewerpanels" -> rejoinWithout(context, "panel_newer");
			case "novalues" -> rejoinWithout(context, "client_value");
			case "facing" -> {
				String facing = context.computeOnClient(client -> client.player.getYRot() + " " + client.player.getXRot());
				LOGGER.info("[M8] looking {}", facing);
			}
			case "type" -> context.getInput().typeChars(words[1]);
			case "panelmouse" -> panelMouse(context, Integer.parseInt(words[1]), Integer.parseInt(words[2]));
			case "panelhover" -> {
				panelCursor(context, Integer.parseInt(words[1]), Integer.parseInt(words[2]));
				context.waitTicks(2);
			}
			case "panelscroll" -> {
				panelCursor(context, Integer.parseInt(words[1]), Integer.parseInt(words[2]));
				context.waitTicks(2);
				context.getInput().scroll(Double.parseDouble(words[3]));
				context.waitTicks(2);
			}
			case "controls" -> {
				context.runOnClient(client -> client.gui.setScreen(new KeyBindsScreen(null, client.options)));
				context.waitTicks(10);
				// With no other mods, the keys of this world's modules come last, because their heading was the last made.
				double[] middle = context.computeOnClient(client -> new double[] {client.getWindow().getScreenWidth() / 2.0, client.getWindow().getScreenHeight() / 2.0});
				context.getInput().setCursorPos(middle[0], middle[1]);
				context.waitTicks(2);
				context.getInput().scroll(-1000);
				context.waitTicks(4);
			}
			case "closescreen" -> context.runOnClient(client -> client.gui.setScreen(null));
			// The very calls the controls menu makes when someone picks a new key.
			case "rebind" -> context.runOnClient(client -> {
				for (KeyMapping key : client.options.keyMappings) {
					if (key.getName().startsWith("key.gm.")) {
						key.setKey(InputConstants.Type.KEYBOARD.getOrCreate(Integer.parseInt(words[1])));
						KeyMapping.resetMapping();
					}
				}
			});
			case "nokeys" -> {
				String keys = context.computeOnClient(client -> Arrays.stream(client.options.keyMappings).filter(key -> key.getName().startsWith("key.gm.")).map(key -> key.getName() + "=" + key.saveString()).toList().toString());
				LOGGER.info("[M8] module keys {}", keys);
			}
			case "guisize" -> {
				String size = context.computeOnClient(client -> {
					AbstractContainerScreenAccessor at = (AbstractContainerScreenAccessor) client.gui.screen();
					return at.companion$leftPos() + " " + at.companion$topPos() + " " + client.getWindow().getGuiScale();
				});
				LOGGER.info("[M8] gui {}", size);
			}
			case "screen" -> {
				String shown = context.computeOnClient(client -> client.gui.screen() == null ? "none" : client.gui.screen().getClass().getSimpleName());
				LOGGER.info("[M8] the screen is {}", shown);
			}
			// The same steps as the game's own language screen.
			case "language" -> {
				context.runOnClient(client -> {
					client.getLanguageManager().setSelected(words[1]);
					client.options.languageCode = words[1];
					client.reloadResourcePacks();
					client.options.save();
					client.options.broadcastOptions();
				});
				context.waitTicks(40);
				context.waitFor(client -> client.gui.overlay() == null, 2 * TICKS_PER_MINUTE);
			}
			case "whatlanguage" -> {
				String shown = context.computeOnClient(client -> client.getLanguageManager().getSelected());
				LOGGER.info("[M8] language {}", shown);
			}
			case "title" -> {
				String shown = context.computeOnClient(client -> client.gui.screen() == null ? "none" : client.gui.screen().getTitle().getString());
				LOGGER.info("[M8] title {}", shown);
			}
			case "hoverhotbar" -> {
				int place = Integer.parseInt(words[1]);
				double[] pixel = context.computeOnClient(client -> {
					AbstractContainerScreen<?> screen = (AbstractContainerScreen<?>) client.gui.screen();
					AbstractContainerScreenAccessor at = (AbstractContainerScreenAccessor) screen;
					Slot found = screen.getMenu().getSlot(FIRST_HOTBAR_SLOT + place);
					double scale = client.getWindow().getGuiScale();
					return new double[] {(at.companion$leftPos() + found.x + 8) * scale, (at.companion$topPos() + found.y + 8) * scale};
				});
				context.getInput().setCursorPos(pixel[0], pixel[1]);
				context.waitTicks(5);
			}
			case "bookpage" -> {
				String shown = context.computeOnClient(client -> client.gui.screen() instanceof BookViewScreen book ? firstPage(book) : "no book");
				LOGGER.info("[M8] book page {}", shown);
			}
			case "menunames" -> {
				String shown = context.computeOnClient(client -> {
					List<String> names = new ArrayList<>();
					for (int slot = 0; slot < client.player.containerMenu.slots.size() - 36; slot++) {
						ItemStack stack = client.player.containerMenu.getSlot(slot).getItem();
						if (!stack.isEmpty()) {
							names.add(stack.getHoverName().getString());
						}
					}
					return String.join(" | ", names);
				});
				LOGGER.info("[M8] menu names {}", shown);
			}
			case "position" -> {
				String where = context.computeOnClient(KnowledgeTest::where);
				LOGGER.info("[M8] position {}", where);
			}
			// A client works out climbing for itself, so this is what shows whether it thinks a block can be climbed.
			case "climb" -> {
				String before = context.computeOnClient(KnowledgeTest::where);
				context.getInput().holdKeyFor(options -> options.keyUp, Integer.parseInt(words[1]));
				String after = context.computeOnClient(KnowledgeTest::where);
				LOGGER.info("[M8] climbed from {} to {}", before, after);
			}
			case "useon" -> context.runOnClient(client -> {
				BlockPos pos = new BlockPos(Integer.parseInt(words[1]), Integer.parseInt(words[2]), Integer.parseInt(words[3]));
				Direction face = Direction.byName(words[4]);
				client.gameMode.useItemOn(client.player, InteractionHand.MAIN_HAND, new BlockHitResult(Vec3.atCenterOf(pos).relative(face, 0.5), face, pos, false));
			});
			case "registry" -> {
				String names = context.computeOnClient(client -> client.level.registryAccess().lookupOrThrow(ResourceKey.<Object>createRegistryKey(Identifier.parse(words[1])))
						.keySet().stream().filter(id -> id.getNamespace().equals("gm")).map(Identifier::toString).sorted().toList().toString());
				LOGGER.info("[M8] registry {} has {}", words[1], names);
			}
			case "advancements" -> {
				String known = context.computeOnClient(KnowledgeTest::advancements);
				LOGGER.info("[M8] advancements: {}", known);
			}
			case "advancementscreen" -> {
				context.getInput().pressKey(options -> options.keyAdvancements);
				context.waitFor(client -> client.gui.screen() != null, TICKS_PER_MINUTE);
				context.waitTicks(20);
				context.takeScreenshot("m8_" + words[1]);
				context.runOnClient(client -> client.gui.setScreen(null));
			}
			case "menubutton" -> context.runOnClient(client -> client.gameMode.handleInventoryButtonClick(client.player.containerMenu.containerId, Integer.parseInt(words[1])));
			case "enchantoffer" -> {
				context.waitTicks(10);
				String offer = context.computeOnClient(client -> {
					EnchantmentMenu menu = (EnchantmentMenu) client.player.containerMenu;
					var enchantments = client.level.registryAccess().lookupOrThrow(Registries.ENCHANTMENT);
					List<String> offers = new ArrayList<>();
					for (int place = 0; place < menu.costs.length; place++) {
						offers.add(menu.costs[place] + " levels: " + (menu.enchantClue[place] < 0 ? "nothing" : enchantments.getKey(enchantments.byId(menu.enchantClue[place]))));
					}
					return offers.toString();
				});
				LOGGER.info("[M8] the table offers {}", offer);
			}
			case "worn" -> {
				String worn = context.computeOnClient(client -> {
					var equippable = client.player.getMainHandItem().get(DataComponents.EQUIPPABLE);
					return equippable == null ? "nothing" : equippable.slot().getName() + " " + equippable.assetId().map(asset -> asset.identifier().toString()).orElse("no art");
				});
				LOGGER.info("[M8] worn as {}", worn);
			}
			case "soundknown" -> {
				String known = context.computeOnClient(client -> client.getSoundManager().getSoundEvent(Identifier.parse(words[1])) == null ? "doesn't have" : "has");
				LOGGER.info("[M8] the pack {} {}", known, words[1]);
			}
			default -> LOGGER.warn("[M8] unknown request {}", request);
		}
		context.waitTicks(10);
	}

	/** The screen keeps what it's showing to itself, and this is only a test. */
	private static String firstPage(BookViewScreen screen) {
		try {
			for (Field field : BookViewScreen.class.getDeclaredFields()) {
				// There's a shared empty one as well, which isn't what this screen's showing.
				if (field.getType() == BookViewScreen.BookAccess.class && !Modifier.isStatic(field.getModifiers())) {
					field.setAccessible(true);
					return ((BookViewScreen.BookAccess) field.get(screen)).getPage(0).getString().replace("\n", " | ");
				}
			}
			return "no pages";
		} catch (IllegalAccessException error) {
			throw new IllegalStateException(error);
		}
	}

	private static String where(Minecraft client) {
		return client.player.getX() + " " + client.player.getY() + " " + client.player.getZ() + " climbing " + client.player.onClimbable() + " on the ground " + client.player.onGround();
	}

	/** What a client has been told of this world's advancements, and which it knows are done. */
	private static String advancements(Minecraft client) {
		ClientAdvancements known = client.player.connection.getAdvancements();
		List<String> found = new ArrayList<>();
		known.tree().nodes().stream().filter(node -> node.holder().id().getNamespace().equals("gm")).forEach(node -> {
			var progress = known.progress().get(node.holder());
			String title = node.advancement().display().map(display -> display.title().getString()).orElse("");
			String icon = node.advancement().display().map(display -> String.valueOf(display.icon().create().get(DataComponents.ITEM_MODEL))).orElse("");
			found.add(node.holder().id() + "=" + title + "|" + icon + "|" + (progress != null && progress.isDone()));
		});
		found.sort(Comparator.naturalOrder());
		return found.toString();
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

	/** The real mouse, at a place on the panel that's open, measured from its top left corner. */
	private void panelMouse(ClientGameTestContext context, int x, int y) {
		panelCursor(context, x, y);
		context.waitTicks(2);
		context.getInput().pressMouse(InputConstants.MOUSE_BUTTON_LEFT);
	}

	private void panelCursor(ClientGameTestContext context, int x, int y) {
		double[] pixel = context.computeOnClient(client -> {
			AbstractContainerScreenAccessor at = (AbstractContainerScreenAccessor) client.gui.screen();
			double scale = client.getWindow().getGuiScale();
			return new double[] {(at.companion$leftPos() + x) * scale, (at.companion$topPos() + y) * scale};
		});
		context.getInput().setCursorPos(pixel[0], pixel[1]);
	}

	/** Which channels it listens on is all a server can see of a companion, so this looks just like one from before that channel. */
	private void rejoinWithout(ClientGameTestContext context, String channel) {
		context.runOnClient(client -> {
			ClientPlayNetworking.unregisterGlobalReceiver(Identifier.fromNamespaceAndPath("gm", channel));
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

	/** Every shapeless recipe in the player's book, as what each of its slots cycles through when shown, going by what's drawn for it. */
	private static void logRecipeBook(ClientGameTestContext context) {
		String shown = context.computeOnClient(client -> {
			ContextMap resolving = SlotDisplayContext.fromLevel(client.level);
			List<List<List<String>>> recipes = new ArrayList<>();
			for (RecipeCollection collection : client.player.getRecipeBook().getCollections()) {
				for (RecipeDisplayEntry entry : collection.getRecipes()) {
					if (entry.display() instanceof ShapelessCraftingRecipeDisplay shapeless) {
						recipes.add(shapeless.ingredients().stream().map(place -> place.resolveForStacks(resolving).stream()
								.map(stack -> String.valueOf(stack.get(DataComponents.ITEM_MODEL))).toList()).toList());
					}
				}
			}
			return new Gson().toJson(recipes);
		});
		LOGGER.info("[M8] recipe book: {}", shown);
	}

	private static void logJei(ClientGameTestContext context, ItemStack makes) {
		List<String> shown = context.computeOnClient(client -> CompanionJeiPlugin.shown(makes));
		LOGGER.info("[M8] jei: {}", new Gson().toJson(shown));
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
