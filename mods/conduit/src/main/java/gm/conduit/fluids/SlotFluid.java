package gm.conduit.fluids;

import eu.pb4.polymer.core.api.utils.PolymerSyncedObject;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.LevelAccessor;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.LiquidBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.material.FlowingFluid;
import net.minecraft.world.level.material.Fluid;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.level.material.Fluids;

/**
 * A blank fluid, which spreads through the world by the game's own rules, with how far and how fast coming from the current release. A client is never told about it
 * by name, because all it has any way to draw is water or lava, and to it that's what this is, so it swims and sinks in step with the server.
 */
public abstract class SlotFluid extends FlowingFluid implements PolymerSyncedObject<Fluid> {
	private static final float BEYOND_ANY_EXPLOSION = 100.0F;
	private final String slotId;
	private SlotFluid other;
	private LiquidBlock block;

	SlotFluid(String slotId) {
		this.slotId = slotId;
	}

	/** A source and its flowing form each need the other, and the block needs both. */
	final void join(SlotFluid other, LiquidBlock block) {
		this.other = other;
		this.block = block;
	}

	final String slotId() {
		return this.slotId;
	}

	@Override
	public Fluid getPolymerReplacement(Fluid fluid, PacketContext context) {
		boolean lava = SlotFluids.settings(this.slotId).lava();
		return isSourceFluid() ? (lava ? Fluids.LAVA : Fluids.WATER) : (lava ? Fluids.FLOWING_LAVA : Fluids.FLOWING_WATER);
	}

	abstract boolean isSourceFluid();

	@Override
	public Fluid getFlowing() {
		return isSourceFluid() ? this.other : this;
	}

	@Override
	public Fluid getSource() {
		return isSourceFluid() ? this : this.other;
	}

	@Override
	public boolean isSame(Fluid fluid) {
		return fluid == this || fluid == this.other;
	}

	@Override
	public Item getBucket() {
		return SlotFluids.settings(this.slotId).bucket();
	}

	@Override
	protected boolean canConvertToSource(ServerLevel level) {
		return SlotFluids.settings(this.slotId).renews();
	}

	@Override
	protected void beforeDestroyingBlock(LevelAccessor level, BlockPos pos, BlockState state) {
		Block.dropResources(state, level, pos, state.hasBlockEntity() ? level.getBlockEntity(pos) : null);
	}

	@Override
	protected int getSlopeFindDistance(LevelReader level) {
		return SlotFluids.settings(this.slotId).reach();
	}

	@Override
	protected int getDropOff(LevelReader level) {
		return SlotFluids.settings(this.slotId).dropOff();
	}

	@Override
	public int getTickDelay(LevelReader level) {
		return SlotFluids.settings(this.slotId).ticks();
	}

	@Override
	protected boolean canBeReplacedWith(FluidState state, BlockGetter level, BlockPos pos, Fluid fluid, Direction direction) {
		return direction == Direction.DOWN && !isSame(fluid);
	}

	@Override
	protected float getExplosionResistance() {
		return BEYOND_ANY_EXPLOSION;
	}

	@Override
	protected BlockState createLegacyBlock(FluidState state) {
		return this.block.defaultBlockState().setValue(LiquidBlock.LEVEL, getLegacyLevel(state));
	}

	static final class Source extends SlotFluid {
		Source(String slotId) {
			super(slotId);
		}

		@Override
		boolean isSourceFluid() {
			return true;
		}

		@Override
		public boolean isSource(FluidState state) {
			return true;
		}

		@Override
		public int getAmount(FluidState state) {
			return FlowingFluid.SOURCE_LEVEL;
		}
	}

	static final class Flowing extends SlotFluid {
		Flowing(String slotId) {
			super(slotId);
		}

		@Override
		boolean isSourceFluid() {
			return false;
		}

		@Override
		protected void createFluidStateDefinition(StateDefinition.Builder<Fluid, FluidState> builder) {
			super.createFluidStateDefinition(builder);
			builder.add(LEVEL);
		}

		@Override
		public boolean isSource(FluidState state) {
			return false;
		}

		@Override
		public int getAmount(FluidState state) {
			return state.getValue(LEVEL);
		}
	}
}
