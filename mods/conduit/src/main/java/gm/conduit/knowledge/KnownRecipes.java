package gm.conduit.knowledge;

import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.context.ContextMap;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.display.FurnaceRecipeDisplay;
import net.minecraft.world.item.crafting.display.RecipeDisplay;
import net.minecraft.world.item.crafting.display.ShapedCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.ShapelessCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.SlotDisplay;
import net.minecraft.world.item.crafting.display.SlotDisplayContext;
import net.minecraft.world.item.crafting.display.SmithingRecipeDisplay;
import net.minecraft.world.item.crafting.display.StonecutterRecipeDisplay;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Tells a player's recipe viewer which of this world's recipes they know. JEI on its own only reads vanilla's recipes
 * from the player's own game, so without this it can't show anything from here. Only what they've earned goes out, so
 * it spoils nothing, and only to a companion that can read it. The companion's KnownRecipes must stay in step with this.
 */
public final class KnownRecipes {
	private static final int CHECK_TICKS = 100;
	private static final int RECIPES_PER_PACKET = 30;
	private static final int MOST_ALTERNATIVES = 16;
	private static final Map<UUID, Set<String>> SENT = new HashMap<>();

	private KnownRecipes() {}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Part.TYPE, Part.CODEC);
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			if (server.getTickCount() % CHECK_TICKS == 0) {
				server.getPlayerList().getPlayers().forEach(KnownRecipes::sendIfChanged);
			}
		});
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> SENT.remove(handler.player.getUUID()));
		// A release can change what a recipe is, and it makes JEI start again too.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> SENT.clear());
	}

	private static void sendIfChanged(ServerPlayer player) {
		if (!ServerPlayNetworking.canSend(player, Part.TYPE)) {
			return;
		}
		Map<String, Shown> known = knownBy(player);
		if (known.keySet().equals(SENT.get(player.getUUID()))) {
			return;
		}
		SENT.put(player.getUUID(), Set.copyOf(known.keySet()));
		List<Shown> recipes = List.copyOf(known.values());
		int parts = Math.max(1, (recipes.size() + RECIPES_PER_PACKET - 1) / RECIPES_PER_PACKET);
		for (int part = 0; part < parts; part++) {
			int end = Math.min(recipes.size(), (part + 1) * RECIPES_PER_PACKET);
			ServerPlayNetworking.send(player, new Part(part, parts, recipes.subList(part * RECIPES_PER_PACKET, end)));
		}
	}

	private static Map<String, Shown> knownBy(ServerPlayer player) {
		Knowledge knowledge = Knowledge.instance();
		KnowledgePlan plan = knowledge.plan();
		ContextMap context = SlotDisplayContext.fromLevel(player.level());
		Map<String, Shown> known = new LinkedHashMap<>();
		// An open recipe is known once it's in the player's book, which happens when they first hold something it uses.
		for (Identifier id : plan.open()) {
			knowledge.recipe(id).filter(holder -> player.getRecipeBook().contains(holder.id()))
					.flatMap(holder -> shown(holder, context)).ifPresent(recipe -> known.put(recipe.id(), recipe));
		}
		for (KnowledgePlan.Entry entry : knowledge.knownEntries(player)) {
			for (Identifier id : entry.recipes()) {
				knowledge.recipe(id).flatMap(holder -> shown(holder, context)).ifPresent(recipe -> known.put(recipe.id(), recipe));
			}
		}
		plan.machines().forEach((machine, recipes) -> {
			for (KnowledgePlan.MachineRecipe recipe : recipes) {
				if (knowledge.mayShow(player, recipe)) {
					known.put(recipe.id(), shown(machine, recipe));
				}
			}
		});
		return known;
	}

	private static Optional<Shown> shown(RecipeHolder<?> holder, ContextMap context) {
		List<RecipeDisplay> displays = holder.value().display();
		if (displays.isEmpty()) {
			return Optional.empty();
		}
		RecipeDisplay display = displays.getFirst();
		int width = 0;
		List<SlotDisplay> slots;
		switch (display) {
			case ShapedCraftingRecipeDisplay shaped -> {
				width = shaped.width();
				slots = shaped.ingredients();
			}
			case ShapelessCraftingRecipeDisplay shapeless -> slots = shapeless.ingredients();
			case FurnaceRecipeDisplay furnace -> slots = List.of(furnace.ingredient());
			case StonecutterRecipeDisplay cutter -> slots = List.of(cutter.input());
			case SmithingRecipeDisplay smithing -> slots = List.of(smithing.template(), smithing.base(), smithing.addition());
			default -> {
				return Optional.empty();
			}
		}
		List<ItemStack> results = display.result().resolveForStacks(context);
		if (results.isEmpty()) {
			return Optional.empty();
		}
		List<List<ItemStack>> inputs = slots.stream()
				.map(slot -> slot.resolveForStacks(context).stream().limit(MOST_ALTERNATIVES).toList())
				.toList();
		List<ItemStack> stations = display.craftingStation().resolveForStacks(context);
		String station = stations.isEmpty() ? "" : stations.getFirst().getHoverName().getString();
		return Optional.of(new Shown(holder.id().identifier().toString(), station, width, inputs, results.getFirst()));
	}

	private static Shown shown(String machine, KnowledgePlan.MachineRecipe recipe) {
		List<List<ItemStack>> inputs = new ArrayList<>();
		for (KnowledgePlan.MachineInput input : recipe.inputs()) {
			inputs.add(List.of(new ItemStack(BuiltInRegistries.ITEM.getValue(Identifier.parse(input.item())), input.count())));
		}
		return new Shown(recipe.id(), readable(machine), 0, inputs, recipe.output());
	}

	/** A machine's recipes are filed under feature/name, and nothing else says what players call it. */
	private static String readable(String machine) {
		String name = machine.substring(machine.lastIndexOf('/') + 1);
		return Arrays.stream(name.split("_")).filter(word -> !word.isEmpty())
				.map(word -> Character.toUpperCase(word.charAt(0)) + word.substring(1)).collect(Collectors.joining(" "));
	}

	private record Shown(String id, String station, int width, List<List<ItemStack>> inputs, ItemStack output) {
		static final StreamCodec<RegistryFriendlyByteBuf, Shown> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Shown::id,
				ByteBufCodecs.STRING_UTF8, Shown::station,
				ByteBufCodecs.VAR_INT, Shown::width,
				ItemStack.OPTIONAL_STREAM_CODEC.apply(ByteBufCodecs.list()).apply(ByteBufCodecs.list()), Shown::inputs,
				ItemStack.OPTIONAL_STREAM_CODEC, Shown::output,
				Shown::new);
	}

	private record Part(int index, int total, List<Shown> recipes) implements CustomPacketPayload {
		static final Type<Part> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "known_recipes"));
		static final StreamCodec<RegistryFriendlyByteBuf, Part> CODEC = StreamCodec.composite(
				ByteBufCodecs.VAR_INT, Part::index,
				ByteBufCodecs.VAR_INT, Part::total,
				Shown.CODEC.apply(ByteBufCodecs.list()), Part::recipes,
				Part::new);

		@Override
		public Type<Part> type() {
			return TYPE;
		}
	}
}
