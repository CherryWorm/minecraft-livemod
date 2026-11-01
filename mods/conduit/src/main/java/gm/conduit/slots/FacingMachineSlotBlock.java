package gm.conduit.slots;

import net.minecraft.resources.Identifier;

/** A machine with a front, like a furnace. Its feature says how it chooses which way that is when it's placed. */
public final class FacingMachineSlotBlock extends MachineSlotBlock {
	public FacingMachineSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
	}

	@Override
	protected boolean turns() {
		return true;
	}
}
