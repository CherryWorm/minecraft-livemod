package gm.conduit.slots;

import eu.pb4.polymer.core.api.block.PolymerBlockUtils;
import eu.pb4.polymer.core.api.item.PolymerBlockItem;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.object.builder.v1.block.entity.FabricBlockEntityTypeBuilder;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntityType;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.IntStream;

/**
 * Registers the whole pool at boot, with meaningless IDs and no content. A world with nothing bound
 * looks and plays like vanilla. What a slot looks like comes from the resource pack and what it does
 * comes from a module, so new content needs no restart, and F3 gives nothing away.
 */
public final class NeutralSlots {
	public static final int FIRST_ITEM_ID = 1;
	public static final int ITEM_COUNT = 1200;

	private static final List<String> BLOCK_IDS = new ArrayList<>();
	private static final List<String> ITEM_IDS = new ArrayList<>();
	private static final List<String> STATE_MODELS = new ArrayList<>();
	private static BlockEntityType<SlotBlockEntity> machineEntityType;

	private NeutralSlots() {}

	public static List<String> blockIds() {
		return List.copyOf(BLOCK_IDS);
	}

	public static List<String> itemIds() {
		return List.copyOf(ITEM_IDS);
	}

	/** The models of each stage or shape of a block that has several, which a client looks for whether or not anything uses that block yet. */
	public static List<String> stateModels() {
		return List.copyOf(STATE_MODELS);
	}

	public static BlockEntityType<SlotBlockEntity> machineEntityType() {
		return machineEntityType;
	}

	public static void register() {
		List<Block> machines = new ArrayList<>();
		for (SlotFamily family : SlotFamily.values()) {
			for (int i = 0; i < family.count(); i++) {
				Block block = registerBlock("s%04d".formatted(family.firstId() + i), family);
				if (family == SlotFamily.MACHINE || family == SlotFamily.MODEL) {
					machines.add(block);
				}
			}
		}
		machineEntityType = Registry.register(BuiltInRegistries.BLOCK_ENTITY_TYPE, id("machine"),
				FabricBlockEntityTypeBuilder.create(SlotBlockEntity::new, machines.toArray(Block[]::new)).build());
		PolymerBlockUtils.registerBlockEntity(machineEntityType);

		for (int i = 0; i < ITEM_COUNT; i++) {
			registerItem("i%04d".formatted(FIRST_ITEM_ID + i));
		}
	}

	private static Block registerBlock(String path, SlotFamily family) {
		Identifier id = id(path);
		Identifier model = id("block/" + path);
		var properties = family.properties().setId(ResourceKey.create(Registries.BLOCK, id));
		Block block = switch (family) {
			case MACHINE -> new MachineSlotBlock(properties, family, model, path);
			case MODEL -> new ModelSlotBlock(properties, family, model, path);
			case CROP -> new CropSlotBlock(properties, family, model, path);
			case CONNECTED -> new ConnectedSlotBlock(properties, family, model, path);
			default -> new SlotBlock(properties, family, model, path);
		};
		Registry.register(BuiltInRegistries.BLOCK, id, block);
		Registry.register(BuiltInRegistries.ITEM, id, new PolymerBlockItem(
				block,
				new Item.Properties().useBlockDescriptionPrefix().setId(ResourceKey.create(Registries.ITEM, id))));
		BLOCK_IDS.add(path);
		if (family == SlotFamily.CROP) {
			IntStream.rangeClosed(0, CropSlotBlock.LAST_STAGE).forEach(stage -> STATE_MODELS.add(CropSlotBlock.stageModel(path, stage)));
		} else if (family == SlotFamily.CONNECTED) {
			IntStream.range(0, ConnectedSlotBlock.shapeCount()).forEach(shape -> STATE_MODELS.add(ConnectedSlotBlock.shapeModel(path, shape)));
		}
		return block;
	}

	private static void registerItem(String path) {
		Identifier id = id(path);
		Registry.register(BuiltInRegistries.ITEM, id,
				new SlotItem(new Item.Properties().setId(ResourceKey.create(Registries.ITEM, id)), path));
		ITEM_IDS.add(path);
	}

	private static Identifier id(String path) {
		return Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path);
	}
}
