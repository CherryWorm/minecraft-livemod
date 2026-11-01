package gm.conduit.entities;

import de.tomalbrc.bil.api.AnimatedEntity;
import de.tomalbrc.bil.core.holder.entity.simple.SimpleEntityHolder;
import de.tomalbrc.bil.core.holder.wrapper.Bone;
import de.tomalbrc.bil.core.model.Model;
import net.minecraft.world.entity.Entity;

/** A model with no hitbox, facing wherever the thing it's showing faces, whether or not anything's animating it. */
final class TurningHolder<T extends Entity & AnimatedEntity> extends SimpleEntityHolder<T> {
	TurningHolder(T parent, Model model) {
		super(parent, model);
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
