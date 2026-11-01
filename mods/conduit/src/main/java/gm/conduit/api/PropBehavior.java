package gm.conduit.api;

import gm.conduit.entities.SlotProp;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;

/** What a prop does, since by itself it does nothing but stand there. Runs on the server. */
public interface PropBehavior {
	default void tick(SlotProp prop) {}

	/** A player clicked on one marked "clickable". It's called once for each hand, so check which one if that matters. */
	default InteractionResult interact(SlotProp prop, Player player, InteractionHand hand) {
		return InteractionResult.PASS;
	}
}
