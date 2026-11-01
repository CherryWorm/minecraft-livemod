package gm.conduit.slots;

import net.minecraft.resources.Identifier;

/** A cube that can face any way. Its feature says how it chooses when it's placed. */
public final class FacingSlotBlock extends SlotBlock {
	public FacingSlotBlock(Properties properties, SlotFamily family, Identifier model, String slotId) {
		super(properties, family, model, slotId);
	}

	@Override
	protected boolean turns() {
		return true;
	}
}
