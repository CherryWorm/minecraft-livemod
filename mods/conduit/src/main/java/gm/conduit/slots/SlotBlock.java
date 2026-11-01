package gm.conduit.slots;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import eu.pb4.polymer.blocks.api.PolymerTexturedBlock;
import gm.conduit.api.BlockBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import org.jspecify.annotations.Nullable;

/** A blank block. Its behaviour comes from whichever module has bound this slot, if any. */
public class SlotBlock extends Block implements PolymerTexturedBlock {
	private static BlockState emptyState;

	private final BlockState polymerState;
	private final String slotId;

	public SlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties);
		this.slotId = slotId;
		this.polymerState = family.modelType() == null
				? emptyState()
				: PolymerBlockResourceUtils.requestBlock(family.modelType(), PolymerBlockModel.of(model));
		if (this.polymerState == null) {
			throw new IllegalStateException("No free " + family.modelType() + " slots for " + slotId);
		}
	}

	/**
	 * What a client sees for a block drawn by a model: a solid block with nothing to draw. It's a leaves-like one because those
	 * don't hide their neighbours' faces, and all model blocks can share it, since they all look the same to a client.
	 */
	private static BlockState emptyState() {
		if (emptyState == null) {
			emptyState = PolymerBlockResourceUtils.requestEmpty(BlockModelType.LEAVES);
		}
		return emptyState;
	}

	public String slotId() {
		return this.slotId;
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		return this.polymerState;
	}

	@Override
	protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior == null || level.isClientSide()) {
			return super.useWithoutItem(state, level, pos, player, hit);
		}
		return ServerModuleHost.instance().guarded(this.slotId, InteractionResult.PASS,
				() -> behavior.use(state, level, pos, player, hit));
	}

	@Override
	public void stepOn(Level level, BlockPos pos, BlockState state, Entity entity) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.stepOn(level, pos, state, entity));
		}
		super.stepOn(level, pos, state, entity);
	}

	/** Called from every block change on a live chunk, because vanilla's own removal hook is skipped by some of them. */
	public void removed(BlockState state, ServerLevel level, BlockPos pos) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.removed(state, level, pos));
		}
	}

	@Override
	protected void randomTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.randomTick(state, level, pos, random));
		}
	}
}
