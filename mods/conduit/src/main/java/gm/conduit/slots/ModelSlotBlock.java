package gm.conduit.slots;

import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.BlockWithElementHolder;
import eu.pb4.polymer.virtualentity.api.ElementHolder;
import net.minecraft.core.BlockPos;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;

/**
 * A machine drawn by a model instead of a textured cube, so it can be any shape and have moving parts. To a client it's
 * a full block with nothing to draw, which gives it a hitbox, with the model standing in that space.
 */
public final class ModelSlotBlock extends MachineSlotBlock implements BlockWithElementHolder {
	private static final String IDLE = "idle";
	/** A holder sits at the block's centre, and a model's feet are at its origin. */
	private static final Vec3 ON_THE_FLOOR = new Vec3(0, -0.5, 0);

	public ModelSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
	}

	@Override
	protected boolean turns() {
		return true;
	}

	@Override
	public ElementHolder createElementHolder(ServerLevel level, BlockPos pos, BlockState state) {
		Model model = BlockModels.model(slotId());
		if (model == null) {
			return null;
		}
		SlotModelHolder holder = new SlotModelHolder(model, state.getValue(FACING), BlockSettings.of(slotId()).glowing());
		if (model.animations().containsKey(IDLE)) {
			holder.getAnimator().playAnimation(IDLE);
		}
		return holder;
	}

	@Override
	public Vec3 getElementHolderOffset(ServerLevel level, BlockPos pos, BlockState state) {
		return ON_THE_FLOOR;
	}

	@Override
	public boolean tickElementHolder(ServerLevel level, BlockPos pos, BlockState state) {
		return true;
	}
}
