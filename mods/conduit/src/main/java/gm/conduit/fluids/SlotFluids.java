package gm.conduit.fluids;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.SoundType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.properties.NoteBlockInstrument;
import net.minecraft.world.level.material.PushReaction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** The pool of blank fluids, and the current release's definitions for them. A fluid's slot is a source, its flowing form and a block, and they're registered at boot like every other slot. */
public final class SlotFluids {
	public static final int FLUID_COUNT = 16;
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "fluids.json");
	private static final List<SlotLiquidBlock> BLOCKS = new ArrayList<>();
	private static final List<String> MODELS = new ArrayList<>();
	private static final Settings NONE = new Settings(false, Items.AIR, false, 4, 1, 5, 0, false);
	private static Map<String, Settings> settings = Map.of();

	/**
	 * @param lava whether a client sees it as lava, and otherwise it sees water
	 * @param bucket what a bucket of it is, or air if it can't be picked up
	 * @param renews whether two sources make a third between them, as water does
	 * @param reach how far it looks for somewhere lower to flow towards
	 * @param dropOff how much it thins with each block it spreads
	 * @param ticks how many ticks each step of spreading takes
	 * @param light how much light it gives
	 * @param surface whether a still pool shows its own picture
	 */
	record Settings(boolean lava, Item bucket, boolean renews, int reach, int dropOff, int ticks, int light, boolean surface) {}

	private SlotFluids() {}

	public static void register() {
		for (int index = 0; index < FLUID_COUNT; index++) {
			String number = "%04d".formatted(index + 1);
			String blockPath = "fb" + number;
			Identifier model = id("block/" + blockPath);
			SlotFluid.Source source = Registry.register(BuiltInRegistries.FLUID, id("fl" + number), new SlotFluid.Source(blockPath));
			SlotFluid.Flowing flowing = Registry.register(BuiltInRegistries.FLUID, id("fl" + number + "_flowing"), new SlotFluid.Flowing(blockPath));
			source.join(flowing);
			flowing.join(source);
			var properties = BlockBehaviour.Properties.of().noCollision().strength(100.0F).pushReaction(PushReaction.POPPED).noLootTable().liquid().replaceable()
					.sound(SoundType.EMPTY).instrument(NoteBlockInstrument.HARP).randomTicks().lightLevel(state -> state.getValue(gm.conduit.slots.SlotBlock.LIGHT))
					.setId(ResourceKey.create(Registries.BLOCK, id(blockPath)));
			SlotLiquidBlock block = Registry.register(BuiltInRegistries.BLOCK, id(blockPath), new SlotLiquidBlock(source, properties, blockPath, model));
			source.setBlock(block);
			flowing.setBlock(block);
			BLOCKS.add(block);
			MODELS.add(blockPath);
		}
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	private static Identifier id(String path) {
		return Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path);
	}

	/** The models of their still pools, which a client looks for whether or not anything uses that slot yet. */
	public static List<String> stateModels() {
		return List.copyOf(MODELS);
	}

	static Settings settings(String slotId) {
		return settings.getOrDefault(slotId, NONE);
	}

	private static void reload() {
		Map<String, Settings> found = new HashMap<>();
		if (Files.exists(FILE)) {
			try {
				JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
				for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
					JsonObject raw = entry.getValue().getAsJsonObject();
					found.put(entry.getKey(), new Settings(
							raw.get("lava").getAsBoolean(),
							raw.has("bucket") ? BuiltInRegistries.ITEM.getValue(Identifier.parse(raw.get("bucket").getAsString())) : Items.AIR,
							raw.get("renews").getAsBoolean(),
							raw.get("reach").getAsInt(),
							raw.get("drop_off").getAsInt(),
							raw.get("ticks").getAsInt(),
							raw.get("light").getAsInt(),
							raw.get("surface").getAsBoolean()));
				}
			} catch (IOException | RuntimeException error) {
				LOGGER.error("Can't read {}", FILE, error);
			}
		}
		settings = found;
		BLOCKS.forEach(SlotLiquidBlock::settingsChanged);
	}
}
