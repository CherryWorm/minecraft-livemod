package gm.conduit.entities;

import de.tomalbrc.bil.core.model.Model;
import eu.pb4.polymer.virtualentity.api.VirtualEntityUtils;
import eu.pb4.polymer.virtualentity.api.data.InteractionEntityData;
import eu.pb4.polymer.virtualentity.api.elements.InteractionElement;
import it.unimi.dsi.fastutil.ints.IntList;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ClientGamePacketListener;
import net.minecraft.network.protocol.game.ClientboundSetEntityDataPacket;
import net.minecraft.network.syncher.SynchedEntityData.DataValue;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import net.minecraft.world.entity.EntityDimensions;

import java.util.List;
import java.util.function.Consumer;

/**
 * A vehicle's model and its hitbox, plus somewhere to sit. A client puts a rider at the very top of what they ride, and the top of
 * the hitbox won't often be where the seat is, so the rider sits on an extra interaction with no width, as tall as the seat is high.
 * A client can't be told to sit someone off to one side of an entity, so build the model around the seat.
 */
final class VehicleHolder extends ClickableHolder<SlotVehicle> {
	private final InteractionElement seat = new InteractionElement();

	VehicleHolder(SlotVehicle parent, Model model, float seatHeight) {
		super(parent, model);
		this.seat.setSendPositionUpdates(false);
		this.seat.setInvisible(true);
		this.seat.setSize(0.0F, seatHeight);
		addElement(this.seat);
	}

	@Override
	protected void startWatchingExtraPackets(ServerGamePacketListenerImpl player, Consumer<Packet<ClientGamePacketListener>> consumer) {
		super.startWatchingExtraPackets(player, consumer);
		// The model library only does this for a rider who sits on the same thing the model does.
		consumer.accept(VirtualEntityUtils.createClientboundSetPassengersPacket(this.hitboxInteraction.getEntityId(), getDisplayIds()));
		if (this.parent.hasPassenger(player.player)) {
			consumer.accept(hitboxWidth(0.0F));
		}
	}

	@Override
	protected void addDirectPassengers(IntList passengers) {
		super.addDirectPassengers(passengers);
		passengers.add(this.seat.getEntityId());
	}

	@Override
	public void onDimensionsUpdated(EntityDimensions dimensions) {
		super.onDimensionsUpdated(dimensions);
		if (this.parent.getFirstPassenger() instanceof ServerPlayer rider) {
			riderSeated(rider);
		}
	}

	/**
	 * Someone sitting inside a hitbox would be clicking on it with everything they did, so for them alone it has no width. It keeps its
	 * height, because that's what the model's parts are measured down from.
	 */
	void riderSeated(ServerPlayer rider) {
		rider.connection.send(hitboxWidth(0.0F));
	}

	void riderGone(ServerPlayer rider) {
		rider.connection.send(hitboxWidth(this.dimensions.width()));
	}

	private ClientboundSetEntityDataPacket hitboxWidth(float width) {
		return new ClientboundSetEntityDataPacket(this.hitboxInteraction.getEntityId(), List.of(DataValue.create(InteractionEntityData.WIDTH, width)));
	}

	@Override
	public int getVehicleId() {
		return this.seat.getEntityId();
	}
}
