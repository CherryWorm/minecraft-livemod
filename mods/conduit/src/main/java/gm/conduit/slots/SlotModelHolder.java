package gm.conduit.slots;

import de.tomalbrc.bil.core.element.PerPlayerTransformableElement;
import de.tomalbrc.bil.core.holder.positioned.PositionedHolder;
import de.tomalbrc.bil.core.holder.wrapper.Bone;
import de.tomalbrc.bil.core.holder.wrapper.DisplayWrapper;
import de.tomalbrc.bil.core.holder.wrapper.ItemBone;
import de.tomalbrc.bil.core.model.Model;
import de.tomalbrc.bil.core.model.Pose;
import eu.pb4.polymer.virtualentity.api.attachment.BlockAwareAttachment;
import eu.pb4.polymer.virtualentity.api.attachment.HolderAttachment;
import eu.pb4.polymer.virtualentity.api.elements.DisplayElement;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.Brightness;
import org.joml.Quaternionf;
import org.joml.Quaternionfc;
import org.joml.Vector3f;
import org.joml.Vector3fc;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Draws a model block, turned the way the block faces and with whatever a module has done to its parts. A part's changes go on top
 * of whatever its animation says, so a module can move something that's also animated. The library works out poses off the main
 * thread, which is why these are kept where that's safe.
 */
final class SlotModelHolder extends PositionedHolder {
	private static final Vector3fc BLOCK_CENTRE = new Vector3f(0, 0.5F, 0);
	private static final float HALF_TURN = (float) Math.PI;
	private static final float QUARTER_TURN = HALF_TURN / 2;
	private static final int NO_TINT = 0xFFFFFF;
	private static final int NOT_SET = -1;

	/** What a module has done to one part. A rotation is on top of its pose, and so are the others. */
	record PartLook(Vector3fc offset, Quaternionfc rotation, Vector3fc scale, int tint, int glow) {
		static final PartLook NONE = new PartLook(new Vector3f(), new Quaternionf(), new Vector3f(1, 1, 1), NO_TINT, NOT_SET);

		PartLook withOffset(Vector3fc wanted) {
			return new PartLook(wanted, this.rotation, this.scale, this.tint, this.glow);
		}

		PartLook withRotation(Quaternionfc wanted) {
			return new PartLook(this.offset, wanted, this.scale, this.tint, this.glow);
		}

		PartLook withScale(Vector3fc wanted) {
			return new PartLook(this.offset, this.rotation, wanted, this.tint, this.glow);
		}

		PartLook withTint(int wanted) {
			return new PartLook(this.offset, this.rotation, this.scale, wanted, this.glow);
		}

		PartLook withGlow(int wanted) {
			return new PartLook(this.offset, this.rotation, this.scale, this.tint, wanted);
		}
	}

	private final Map<String, PartLook> looks = new ConcurrentHashMap<>();
	private volatile Quaternionfc facing;

	SlotModelHolder(Model model, Direction facing, List<String> glowing) {
		super(model);
		this.facing = turn(facing);
		for (String part : glowing) {
			setLook(part, PartLook.NONE.withGlow(Brightness.FULL_BRIGHT.block()));
		}
	}

	/** How far round a model has to go, when one that's not turned at all faces north. */
	private static Quaternionfc turn(Direction facing) {
		return switch (facing) {
			case NORTH -> null;
			case EAST -> new Quaternionf().rotateY(-QUARTER_TURN);
			case SOUTH -> new Quaternionf().rotateY(HALF_TURN);
			case WEST -> new Quaternionf().rotateY(QUARTER_TURN);
			case UP -> new Quaternionf().rotateX(QUARTER_TURN);
			case DOWN -> new Quaternionf().rotateX(-QUARTER_TURN);
		};
	}

	/** Only for the block turning after it's been placed, which a module can do by changing its state. */
	@Override
	public void notifyUpdate(HolderAttachment.UpdateType type) {
		super.notifyUpdate(type);
		if (type == BlockAwareAttachment.BLOCK_STATE_UPDATE && getAttachment() instanceof BlockAwareAttachment attachment
				&& attachment.getBlockState().getBlock() instanceof SlotBlock block && block.turns()) {
			this.facing = turn(attachment.getBlockState().getValue(SlotBlock.FACING));
			redraw();
		}
	}

	PartLook look(String part) {
		return this.looks.getOrDefault(part, PartLook.NONE);
	}

	/** Returns false if its model has no part of that name, which a module should hear about. */
	boolean setLook(String part, PartLook look) {
		Bone<?> bone = getBone(part);
		if (bone == null) {
			return false;
		}
		this.looks.put(part, look);
		if (bone instanceof ItemBone item) {
			item.updateColor(look.tint());
		}
		if (bone.element() instanceof DisplayElement element) {
			element.setBrightness(look.glow() == NOT_SET ? null : new Brightness(look.glow(), look.glow()));
		}
		show(bone);
		return true;
	}

	/** Back to how its model and animations say it should look, apart from glowing, which belongs to its feature. */
	void clearLook(String part) {
		if (this.looks.containsKey(part)) {
			setLook(part, look(part).glow() == NOT_SET ? PartLook.NONE : PartLook.NONE.withGlow(look(part).glow()));
			this.looks.remove(part);
		}
	}

	private void redraw() {
		for (Bone<?> bone : getBones()) {
			show(bone);
		}
	}

	/** A bone nothing's animating doesn't get asked about, so it has to be told. */
	private void show(Bone<?> bone) {
		Pose last = bone.getLastPose(null);
		updateElement(null, bone, last != null ? last : bone.getDefaultPose());
	}

	@Override
	protected void applyPose(ServerPlayer player, Pose pose, DisplayWrapper<?> display) {
		PartLook look = this.looks.get(display.name());
		Quaternionfc turned = this.facing;
		if (look == null && turned == null) {
			super.applyPose(player, pose, display);
			return;
		}
		Vector3f translation = new Vector3f(pose.readOnlyTranslation());
		Quaternionf rotation = new Quaternionf(pose.readOnlyLeftRotation());
		Vector3f scale = new Vector3f(pose.readOnlyScale());
		if (look != null) {
			translation.add(look.offset());
			rotation.mul(look.rotation());
			scale.mul(look.scale());
		}
		if (turned != null) {
			translation.sub(BLOCK_CENTRE).rotate(turned).add(BLOCK_CENTRE);
			rotation.premul(turned);
		}
		PerPlayerTransformableElement element = display.element();
		element.setScale(player, scale);
		element.setTranslation(player, translation);
		element.setLeftRotation(player, rotation);
		element.setRightRotation(player, pose.readOnlyRightRotation());
		element.startInterpolationIfDirty(player);
	}
}
