package gm.conduit.entities;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.core.holder.entity.simple.InteractableEntityHolder;
import de.tomalbrc.bil.core.holder.wrapper.Bone;
import de.tomalbrc.bil.core.model.Model;
import net.minecraft.world.entity.Entity;

/** A model with a hitbox, facing wherever the thing it's showing faces. The model library only turns the parts an animation is moving. */
class ClickableHolder<T extends Entity & AnimatedEntity> extends InteractableEntityHolder<T> {
	ClickableHolder(T parent, Model model) {
		super(parent, model);
		// All of it rides the entity, which is what keeps it together, so it doesn't need telling where it is as well.
		this.hitboxInteraction.setSendPositionUpdates(false);
	}

	@Override
	protected void onAsyncTick() {
		for (Bone<?> bone : this.bones) {
			bone.element().setYaw(this.parent.getYRot());
			bone.element().setPitch(this.parent.getXRot());
		}
		super.onAsyncTick();
	}
}
