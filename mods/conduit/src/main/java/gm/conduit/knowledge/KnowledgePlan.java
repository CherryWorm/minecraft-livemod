package gm.conduit.knowledge;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.world.item.ItemStack;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** The discovery plan for this world, as the broker compiled it. It's replaced as a whole on each release. */
public record KnowledgePlan(
		boolean shared,
		Map<String, Entry> entries,
		Map<Identifier, List<String>> gated,
		List<Identifier> open,
		Map<String, List<MachineRecipe>> machines,
		Map<String, String> names) {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "knowledge.json");

	public static final KnowledgePlan EMPTY = new KnowledgePlan(true, Map.of(), Map.of(), List.of(), Map.of(), Map.of());

	/** The requires field is entries a player has to know before this route does anything for them. */
	public record Route(String type, String id, int needed, List<String> requires) {}

	/** The guide field is what a player's book calls this entry, which is also what turns its page on. */
	public record Entry(String id, String title, String text, List<Identifier> recipes, List<Route> routes, String guide) {}

	public record MachineInput(String item, int count) {}

	public record MachineRecipe(String id, String mode, List<MachineInput> inputs, List<MachineInput> outputs, List<String> needs) {
		/** What the agent's told a player found, which only needs to be one thing. */
		public String outputItem() {
			return this.outputs.getFirst().item();
		}

		/** The first of what it makes, for anything that only has room to show one. */
		public ItemStack output() {
			return stack(this.outputs.getFirst());
		}

		public List<ItemStack> outputStacks() {
			return this.outputs.stream().map(MachineRecipe::stack).toList();
		}

		public List<ItemStack> inputStacks() {
			return this.inputs.stream().map(MachineRecipe::stack).toList();
		}

		private static ItemStack stack(MachineInput what) {
			return new ItemStack(BuiltInRegistries.ITEM.getValue(Identifier.parse(what.item())), what.count());
		}
	}

	public List<Entry> withRoute(String type, String id) {
		List<Entry> found = new ArrayList<>();
		for (Entry entry : this.entries.values()) {
			for (Route route : entry.routes()) {
				if (route.type().equals(type) && route.id().equals(id)) {
					found.add(entry);
					break;
				}
			}
		}
		return found;
	}

	static KnowledgePlan read() {
		if (!Files.exists(FILE)) {
			return EMPTY;
		}
		try {
			return parse(new Gson().fromJson(Files.readString(FILE), JsonObject.class));
		} catch (IOException | RuntimeException error) {
			// Nothing is gated while this is broken, because locking players out of what they've earned is worse.
			LOGGER.error("Can't read {}", FILE, error);
			return EMPTY;
		}
	}

	private static MachineInput machineStack(JsonObject json) {
		return new MachineInput(json.get("item").getAsString(), json.get("count").getAsInt());
	}

	private static KnowledgePlan parse(JsonObject json) {
		Map<String, Entry> entries = new LinkedHashMap<>();
		for (Map.Entry<String, JsonElement> item : json.getAsJsonObject("entries").entrySet()) {
			JsonObject entry = item.getValue().getAsJsonObject();
			List<Identifier> recipes = new ArrayList<>();
			entry.getAsJsonArray("recipes").forEach(id -> recipes.add(Identifier.parse(id.getAsString())));
			List<Route> routes = new ArrayList<>();
			entry.getAsJsonArray("routes").forEach(route -> {
				JsonObject object = route.getAsJsonObject();
				// A release from before routes could need anything has none.
				List<String> requires = new ArrayList<>();
				if (object.has("requires")) {
					object.getAsJsonArray("requires").forEach(need -> requires.add(need.getAsString()));
				}
				routes.add(new Route(object.get("type").getAsString(), object.get("id").getAsString(),
						object.has("needed") ? object.get("needed").getAsInt() : 1, requires));
			});
			// A release from before the book has none, and reading it mustn't fail, because that would unlock every recipe.
			String guide = entry.has("guide") ? entry.get("guide").getAsString() : "";
			entries.put(item.getKey(), new Entry(item.getKey(), entry.get("title").getAsString(), entry.get("text").getAsString(), recipes, routes, guide));
		}

		Map<Identifier, List<String>> gated = new HashMap<>();
		for (Map.Entry<String, JsonElement> item : json.getAsJsonObject("gated").entrySet()) {
			List<String> needs = new ArrayList<>();
			item.getValue().getAsJsonArray().forEach(need -> needs.add(need.getAsString()));
			gated.put(Identifier.parse(item.getKey()), needs);
		}

		List<Identifier> open = new ArrayList<>();
		json.getAsJsonArray("open").forEach(id -> open.add(Identifier.parse(id.getAsString())));

		Map<String, List<MachineRecipe>> machines = new HashMap<>();
		for (Map.Entry<String, JsonElement> item : json.getAsJsonObject("machines").entrySet()) {
			List<MachineRecipe> recipes = new ArrayList<>();
			item.getValue().getAsJsonArray().forEach(element -> {
				JsonObject recipe = element.getAsJsonObject();
				List<MachineInput> inputs = new ArrayList<>();
				recipe.getAsJsonArray("inputs").forEach(input -> inputs.add(machineStack(input.getAsJsonObject())));
				List<String> needs = new ArrayList<>();
				recipe.getAsJsonArray("needs").forEach(need -> needs.add(need.getAsString()));
				// A release from before machines could make several things only has the one.
				List<MachineInput> outputs = new ArrayList<>();
				if (recipe.has("outputs")) {
					recipe.getAsJsonArray("outputs").forEach(output -> outputs.add(machineStack(output.getAsJsonObject())));
				} else {
					outputs.add(machineStack(recipe.getAsJsonObject("output")));
				}
				recipes.add(new MachineRecipe(recipe.get("id").getAsString(), recipe.get("mode").getAsString(), inputs, outputs, needs));
			});
			machines.put(item.getKey(), recipes);
		}

		Map<String, String> names = new HashMap<>();
		json.getAsJsonObject("names").entrySet().forEach(item -> names.put(item.getKey(), item.getValue().getAsString()));
		return new KnowledgePlan(!"per_player".equals(json.get("scope").getAsString()), entries, gated, open, machines, names);
	}
}
