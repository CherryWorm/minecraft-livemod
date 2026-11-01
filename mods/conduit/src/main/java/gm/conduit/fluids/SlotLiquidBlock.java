package gm.conduit.fluids;

import eu.pb4.polymer.blocks.api.BlockModelType;
import eu.pb4.polymer.blocks.api.PolymerBlockModel;
import eu.pb4.polymer.blocks.api.PolymerBlockResourceUtils;
import eu.pb4.polymer.blocks.api.PolymerTexturedBlock;
import gm.conduit.api.BlockBehavior;
import gm.conduit.modules.ServerModuleHost;
import gm.conduit.slots.SlotBlock;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.InsideBlockEffectApplier;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.LiquidBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.material.FlowingFluid;
import org.jspecify.annotations.Nullable;

/**
 * A fluid as a block in the world. To a client it's water or lava at the same level, because nothing else can flow or be swum in. A still pool can look like something else
 * all the same, with a stand-in that a client takes for water with a plant in it, whose picture fills the block. There aren't many of those, and the plant has no way to be see-through.
 */
public final class SlotLiquidBlock extends LiquidBlock implements PolymerTexturedBlock {
	private final String slotId;
	private final BlockState surface;

	SlotLiquidBlock(FlowingFluid fluid, Properties properties, String slotId, Identifier model) {
		super(fluid, properties);
		this.slotId = slotId;
		this.surface = PolymerBlockResourceUtils.requestBlock(BlockModelType.KELP, PolymerBlockModel.of(model));
	}

	String slotId() {
		return this.slotId;
	}

	@Override
	protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
		super.createBlockStateDefinition(builder);
		builder.add(SlotBlock.LIGHT);
	}

	/** A release can change how much light new ones give, in the same way as a block. */
	void settingsChanged() {
		registerDefaultState(defaultBlockState().setValue(SlotBlock.LIGHT, SlotFluids.settings(this.slotId).light()));
	}

	@Override
	public BlockState getPolymerBlockState(BlockState state, @Nullable PacketContext context) {
		SlotFluids.Settings settings = SlotFluids.settings(this.slotId);
		if (settings.surface() && this.surface != null && state.getValue(LEVEL) == 0) {
			return this.surface;
		}
		return (settings.lava() ? Blocks.LAVA : Blocks.WATER).defaultBlockState().setValue(LEVEL, state.getValue(LEVEL));
	}

	@Override
	protected void entityInside(BlockState state, Level level, BlockPos pos, Entity entity, InsideBlockEffectApplier effects, boolean precise) {
		super.entityInside(state, level, pos, entity, effects, precise);
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null && !level.isClientSide()) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.entityInside(state, level, pos, entity));
		}
	}

	@Override
	protected void randomTick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {
		super.randomTick(state, level, pos, random);
		BlockBehavior behavior = ServerModuleHost.instance().blockBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.randomTick(state, level, pos, random));
		}
	}
}
