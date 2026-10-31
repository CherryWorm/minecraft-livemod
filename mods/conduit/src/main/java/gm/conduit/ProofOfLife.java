package gm.conduit;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import eu.pb4.polymer.blocks.api.PolymerTexturedBlock;
import eu.pb4.polymer.core.api.item.PolymerBlockItem;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import org.jspecify.annotations.Nullable;

/**
 * One block that proves the pipeline works end to end: a custom block, on a plain client, through
 * the proxy, with its texture from the server's resource pack. M3 replaces this with neutral slots,
 * because a real world starts blank.
 */
final class ProofOfLife {
	private static final Identifier ID = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "s0000");
	private static final Identifier MODEL = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "block/s0000");

	private ProofOfLife() {}

	static void register() {
		Block block = Registry.register(BuiltInRegistries.BLOCK, ID, new ProofBlock(
				BlockBehaviour.Properties.of()
						.strength(1.0f)
						.setId(ResourceKey.create(Registries.BLOCK, ID))));

		Item item = Registry.register(BuiltInRegistries.ITEM, ID, new PolymerBlockItem(
				block,
				new Item.Properties()
						.useBlockDescriptionPrefix()
						.setId(ResourceKey.create(Registries.ITEM, ID))));

		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
			var inventory = handler.player.getInventory();
			if (!inventory.hasAnyMatching(stack -> stack.is(item))) {
				inventory.add(new ItemStack(item, 8));
			}
		});
	}

	private static final class ProofBlock extends Block implements PolymerTexturedBlock {
		private final BlockState polymerState;

		ProofBlock(Properties properties) {
			super(properties);
			this.polymerState = PolymerBlockResourceUtils.requestBlock(BlockModelType.FULL_BLOCK, PolymerBlockModel.of(MODEL));
			if (this.polymerState == null) {
				throw new IllegalStateException("No free FULL_BLOCK slots for " + ID);
			}
		}

		@Override
		public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
			return this.polymerState;
		}
	}
}
