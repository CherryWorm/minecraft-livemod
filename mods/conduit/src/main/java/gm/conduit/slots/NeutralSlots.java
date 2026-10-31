package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import eu.pb4.polymer.blocks.api.PolymerTexturedBlock;
import eu.pb4.polymer.core.api.item.PolymerBlockItem;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import org.jspecify.annotations.Nullable;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Blocks registered at boot with meaningless IDs and no content. What each one looks like comes from
 * the resource pack, so new art needs no restart and F3 gives nothing away.
 */
public final class NeutralSlots {
	private static final Path COUNT_FILE = Path.of("config", "conduit", "slots");
	private static final int DEFAULT_COUNT = 8;
	private static final List<String> IDS = new ArrayList<>();

	private NeutralSlots() {}

	public static List<String> ids() {
		return List.copyOf(IDS);
	}

	public static void register() {
		int count = readCount();
		for (int i = 1; i <= count; i++) {
			registerSlot("s%04d".formatted(i));
		}
	}

	private static void registerSlot(String path) {
		Identifier id = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path);
		Identifier model = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "block/" + path);

		Block block = Registry.register(BuiltInRegistries.BLOCK, id, new SlotBlock(
				BlockBehaviour.Properties.of()
						.strength(1.0f)
						.setId(ResourceKey.create(Registries.BLOCK, id)),
				model));

		Registry.register(BuiltInRegistries.ITEM, id, new PolymerBlockItem(
				block,
				new Item.Properties()
						.useBlockDescriptionPrefix()
						.setId(ResourceKey.create(Registries.ITEM, id))));

		IDS.add(path);
	}

	private static int readCount() {
		try {
			return Files.exists(COUNT_FILE) ? Integer.parseInt(Files.readString(COUNT_FILE).trim()) : DEFAULT_COUNT;
		} catch (IOException | NumberFormatException error) {
			throw new IllegalStateException("Can't read " + COUNT_FILE, error);
		}
	}

	private static final class SlotBlock extends Block implements PolymerTexturedBlock {
		private final BlockState polymerState;

		SlotBlock(Properties properties, Identifier model) {
			super(properties);
			this.polymerState = PolymerBlockResourceUtils.requestBlock(BlockModelType.FULL_BLOCK, PolymerBlockModel.of(model));
			if (this.polymerState == null) {
				throw new IllegalStateException("No free FULL_BLOCK slots for " + model);
			}
		}

		@Override
		public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
			return this.polymerState;
		}
	}
}
