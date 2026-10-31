package gm.conduit.knowledge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import gm.conduit.api.MachineAttempt;
import gm.conduit.bridge.Bridge;
import net.fabricmc.fabric.api.entity.event.v1.ServerEntityCombatEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.event.player.UseBlockCallback;
import net.fabricmc.fabric.api.event.player.UseEntityCallback;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.level.storage.LevelResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * How recipes are found in this world. The agent writes a plan for each world, and the broker turns it into
 * config/conduit/knowledge.json. This class enforces it: a gated recipe can't be crafted until it's learned,
 * and players learn things by finding, examining, killing, reading or piecing them together.
 *
 * <p>Everything here is plain rules with no model involved, so nobody can talk their way into a recipe.
 */
public final class Knowledge {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Knowledge INSTANCE = new Knowledge();
	private static final int SCAN_EVERY_TICKS = 20;

	private KnowledgePlan plan = KnowledgePlan.EMPTY;
	private KnowledgeLedger ledger;
	private MinecraftServer server;
	private Map<Item, List<KnowledgePlan.Entry>> learnedByHolding = Map.of();
	private Map<Item, List<RecipeHolder<?>>> openRecipesByIngredient = Map.of();

	private Knowledge() {}

	public static Knowledge instance() {
		return INSTANCE;
	}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			INSTANCE.server = server;
			INSTANCE.ledger = new KnowledgeLedger(server.getWorldPath(LevelResource.ROOT).resolve("conduit_knowledge.json"));
			INSTANCE.reload();
		});
		// A release copies the config first and then reloads data packs, so this picks up both together.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> {
			if (INSTANCE.ledger != null) {
				INSTANCE.reload();
			}
		});
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			if (server.getTickCount() % SCAN_EVERY_TICKS == 0) {
				server.getPlayerList().getPlayers().forEach(INSTANCE::scanInventory);
			}
		});

		UseBlockCallback.EVENT.register((player, level, hand, hit) -> {
			if (level.isClientSide() || !isExamining(player, hand)) {
				return InteractionResult.PASS;
			}
			String block = BuiltInRegistries.BLOCK.getKey(level.getBlockState(hit.getBlockPos()).getBlock()).toString();
			return INSTANCE.examine((ServerPlayer) player, block);
		});
		UseEntityCallback.EVENT.register((player, level, hand, entity, hit) -> {
			if (level.isClientSide() || !isExamining(player, hand)) {
				return InteractionResult.PASS;
			}
			return INSTANCE.examine((ServerPlayer) player, BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
		});
		ServerEntityCombatEvents.AFTER_KILLED_OTHER_ENTITY.register((level, killer, killed, source) -> {
			if (killer instanceof ServerPlayer player) {
				String type = BuiltInRegistries.ENTITY_TYPE.getKey(killed.getType()).toString();
				INSTANCE.plan.withRoute("kill", type).forEach(entry -> INSTANCE.learn(player, entry));
				String name = INSTANCE.plan.names().get(type);
				if (name != null && INSTANCE.ledger.markFound(player.getStringUUID(), type)) {
					INSTANCE.emitDiscovery(player, name);
				}
			}
		});
	}

	private static boolean isExamining(Player player, InteractionHand hand) {
		return hand == InteractionHand.MAIN_HAND && player.isShiftKeyDown() && player.getMainHandItem().isEmpty();
	}

	private void reload() {
		this.plan = KnowledgePlan.read();
		Map<Item, List<KnowledgePlan.Entry>> holding = new IdentityHashMap<>();
		for (KnowledgePlan.Entry entry : this.plan.entries().values()) {
			for (KnowledgePlan.Route route : entry.routes()) {
				if (route.type().equals("obtain")) {
					item(route.id()).ifPresent(item -> holding.computeIfAbsent(item, key -> new ArrayList<>()).add(entry));
				}
			}
		}
		this.learnedByHolding = holding;

		// An open recipe shows up in the book once you hold something it uses, as vanilla's do.
		Map<Item, List<RecipeHolder<?>>> open = new IdentityHashMap<>();
		for (Identifier id : this.plan.open()) {
			recipe(id).ifPresent(holder -> {
				for (Ingredient ingredient : holder.value().placementInfo().ingredients()) {
					ingredient.items().map(Holder::value).forEach(item -> open.computeIfAbsent(item, key -> new ArrayList<>()).add(holder));
				}
			});
		}
		this.openRecipesByIngredient = open;
		LOGGER.info("knowledge plan: {} entries, {} gated recipes, {} open recipes", this.plan.entries().size(), this.plan.gated().size(), this.plan.open().size());
	}

	private static Optional<Item> item(String id) {
		Identifier parsed = Identifier.tryParse(id);
		return parsed == null ? Optional.empty() : BuiltInRegistries.ITEM.getOptional(parsed);
	}

	private Optional<RecipeHolder<?>> recipe(Identifier id) {
		ResourceKey<Recipe<?>> key = ResourceKey.create(Registries.RECIPE, id);
		return this.server.getRecipeManager().byKey(key);
	}

	private String scopeKey(Player player) {
		return this.plan.shared() ? KnowledgeLedger.SHARED : player.getStringUUID();
	}

	public boolean knows(Player player, String entry) {
		return this.ledger != null && this.ledger.knows(scopeKey(player), entry);
	}

	/** The rule that gates crafting. A recipe nobody has declared isn't ours to restrict. */
	public boolean canUse(Player player, Identifier recipe) {
		List<String> needs = this.plan.gated().get(recipe);
		if (needs == null) {
			return true;
		}
		for (String entry : needs) {
			if (knows(player, entry)) {
				return true;
			}
		}
		return false;
	}

	public void learn(ServerPlayer player, KnowledgePlan.Entry entry) {
		if (!this.ledger.learn(scopeKey(player), entry.id())) {
			return;
		}
		List<ServerPlayer> learners = this.plan.shared() ? this.server.getPlayerList().getPlayers() : List.of(player);
		for (ServerPlayer learner : learners) {
			learner.awardRecipes(recipesOf(entry));
			learner.sendSystemMessage(Component.literal("§6✦ §rYou've learned §e" + entry.title() + "§r. Type §7/codex§r to read it."));
		}
		player.level().playSound(null, player.blockPosition(), SoundEvents.ENCHANTMENT_TABLE_USE, SoundSource.PLAYERS, 1.0F, 1.0F);
		emitDiscovery(player, "learned " + entry.title());
		LOGGER.info("{} learned {}", player.getGameProfile().name(), entry.id());
	}

	/** Looks up an entry by its full name, for modules that teach something themselves. */
	public void learn(ServerPlayer player, String entry) {
		KnowledgePlan.Entry found = this.plan.entries().get(entry);
		if (found == null) {
			throw new IllegalArgumentException("No knowledge called " + entry);
		}
		learn(player, found);
	}

	private List<RecipeHolder<?>> recipesOf(KnowledgePlan.Entry entry) {
		List<RecipeHolder<?>> holders = new ArrayList<>();
		for (Identifier id : entry.recipes()) {
			recipe(id).ifPresent(holders::add);
		}
		return holders;
	}

	private InteractionResult examine(ServerPlayer player, String target) {
		boolean taught = false;
		for (KnowledgePlan.Entry entry : this.plan.withRoute("examine", target)) {
			if (!knows(player, entry.id())) {
				learn(player, entry);
				taught = true;
			}
		}
		return taught ? InteractionResult.SUCCESS : InteractionResult.PASS;
	}

	/** Called when a slot item is used. Returns true if it was something to read, which uses it up. */
	public boolean useItem(ServerPlayer player, ItemStack stack) {
		String item = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
		boolean used = false;
		for (KnowledgePlan.Entry entry : this.plan.withRoute("read", item)) {
			if (!knows(player, entry.id())) {
				learn(player, entry);
				used = true;
			}
		}
		for (KnowledgePlan.Entry entry : this.plan.entries().values()) {
			for (KnowledgePlan.Route route : entry.routes()) {
				if (route.type().equals("fragments") && route.id().equals(item) && !knows(player, entry.id())) {
					int have = this.ledger.addFragment(scopeKey(player), entry.id());
					player.sendSystemMessage(Component.literal("§6✦ §rA piece of something. §7(" + have + " of " + route.needed() + ")"));
					if (have >= route.needed()) {
						learn(player, entry);
					}
					used = true;
				}
			}
		}
		if (used) {
			stack.consume(1, player);
		}
		return used;
	}

	private void scanInventory(ServerPlayer player) {
		if (this.ledger == null) {
			return;
		}
		String key = player.getStringUUID();
		List<ItemStack> stacks = player.getInventory().getNonEquipmentItems();
		for (ItemStack stack : stacks) {
			if (stack.isEmpty()) {
				continue;
			}
			Item item = stack.getItem();
			List<KnowledgePlan.Entry> entries = this.learnedByHolding.get(item);
			if (entries != null) {
				for (KnowledgePlan.Entry entry : entries) {
					learn(player, entry);
				}
			}
			List<RecipeHolder<?>> open = this.openRecipesByIngredient.get(item);
			if (open != null && open.stream().anyMatch(holder -> !player.getRecipeBook().contains(holder.id()))) {
				player.awardRecipes(open);
			}
			String id = BuiltInRegistries.ITEM.getKey(item).toString();
			String name = this.plan.names().get(id);
			if (name != null && this.ledger.markFound(key, id)) {
				emitDiscovery(player, name);
			}
		}
	}

	private void emitDiscovery(ServerPlayer player, String what) {
		JsonObject event = Bridge.event("discovery", player);
		event.addProperty("what", what);
		Bridge.emit(event);
	}

	/**
	 * Checks what a player put in a machine. Order doesn't matter. Near misses are reported so the machine
	 * can react, which is what makes experimenting fun rather than blind.
	 */
	public MachineAttempt attempt(Player player, String machine, List<ItemStack> inputs) {
		int closest = 0;
		int needed = 0;
		boolean locked = false;
		List<ItemStack> offered = inputs.stream().filter(stack -> !stack.isEmpty()).toList();
		for (KnowledgePlan.MachineRecipe recipe : this.plan.machines().getOrDefault(machine, List.of())) {
			int matched = matching(recipe, offered);
			boolean exact = matched == recipe.inputs().size() && offered.size() == recipe.inputs().size();
			if (exact) {
				if (recipe.mode().equals("known") && recipe.needs().stream().noneMatch(entry -> knows(player, entry))) {
					locked = true;
					continue;
				}
				if (player instanceof ServerPlayer serverPlayer && this.ledger.markFound(scopeKey(player), "machine:" + recipe.id())) {
					emitDiscovery(serverPlayer, "a machine recipe: " + this.plan.names().getOrDefault(recipe.outputItem(), recipe.outputItem()));
				}
				return new MachineAttempt(recipe.output(), recipe.inputs().size(), recipe.inputs().size(), false);
			}
			if (matched > closest || (matched == closest && recipe.inputs().size() < needed)) {
				closest = matched;
				needed = recipe.inputs().size();
			}
		}
		return new MachineAttempt(ItemStack.EMPTY, closest, needed, locked);
	}

	private static int matching(KnowledgePlan.MachineRecipe recipe, List<ItemStack> offered) {
		List<ItemStack> left = new ArrayList<>(offered);
		int matched = 0;
		for (KnowledgePlan.MachineInput input : recipe.inputs()) {
			for (int index = 0; index < left.size(); index++) {
				ItemStack stack = left.get(index);
				if (stack.getCount() >= input.count() && BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(input.item())) {
					left.remove(index);
					matched++;
					break;
				}
			}
		}
		return matched;
	}

	/** What players call one of our items. The server has no language files, so it can't work this out from the stack. */
	public String nameOf(ItemStack stack) {
		String name = this.plan.names().get(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
		return name != null ? name : stack.getHoverName().getString();
	}

	public List<KnowledgePlan.Entry> knownEntries(Player player) {
		return this.plan.entries().values().stream().filter(entry -> knows(player, entry.id())).toList();
	}

	/** What the agent's director and watcher see of progress. Names only, and only what's already released. */
	public JsonElement progress() {
		JsonObject out = new JsonObject();
		JsonObject players = new JsonObject();
		for (ServerPlayer player : this.server.getPlayerList().getPlayers()) {
			JsonObject entry = new JsonObject();
			JsonArray found = new JsonArray();
			for (String id : this.ledger.found(player.getStringUUID())) {
				String name = this.plan.names().get(id);
				if (name != null) {
					found.add(name);
				}
			}
			JsonArray known = new JsonArray();
			knownEntries(player).forEach(item -> known.add(item.title()));
			entry.add("found", found);
			entry.add("known", known);
			players.add(player.getGameProfile().name(), entry);
		}
		out.add("online", players);
		JsonArray reached = new JsonArray();
		for (String id : this.ledger.foundByAnyone()) {
			String name = this.plan.names().get(id);
			if (name != null) {
				reached.add(name);
			}
		}
		out.add("reached", reached);
		JsonArray unknown = new JsonArray();
		for (KnowledgePlan.Entry entry : this.plan.entries().values()) {
			boolean anyone = this.server.getPlayerList().getPlayers().stream().anyMatch(player -> knows(player, entry.id()));
			if (!anyone) {
				unknown.add(entry.title());
			}
		}
		out.add("undiscovered", unknown);
		return out;
	}

	public Map<String, Integer> counts() {
		Map<String, Integer> counts = new HashMap<>();
		counts.put("entries", this.plan.entries().size());
		counts.put("gated", this.plan.gated().size());
		return counts;
	}
}
