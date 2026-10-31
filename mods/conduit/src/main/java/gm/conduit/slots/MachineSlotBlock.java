package gm.conduit.slots;

import net.minecraft.core.BlockPos;
import net.minecraft.resources.Identifier;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.EntityBlock;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.BlockEntityTicker;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockState;
import org.jspecify.annotations.Nullable;

/** A blank block that can hold data and run every tick, which is what machines need. */
public class MachineSlotBlock extends SlotBlock implements EntityBlock {
	public MachineSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
	}

	@Override
	public BlockEntity newBlockEntity(BlockPos pos, BlockState state) {
		return new SlotBlockEntity(pos, state);
	}

	@Override
	public <T extends BlockEntity> @Nullable BlockEntityTicker<T> getTicker(Level level, BlockState state, BlockEntityType<T> type) {
		return level.isClientSide() || type != NeutralSlots.machineEntityType()
				? null
				: (tickLevel, pos, tickState, entity) -> ((SlotBlockEntity) entity).tick(this.slotId());
	}
}
