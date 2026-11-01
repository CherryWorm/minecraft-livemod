package gm.feature.rides;

import gm.conduit.api.Beam;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.ProjectileBehavior;
import gm.conduit.api.PropBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.VehicleBehavior;
import gm.conduit.entities.SlotProjectile;
import gm.conduit.entities.SlotProp;
import gm.conduit.entities.SlotVehicle;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;

/** Test fixture: says in chat whenever anything happens to one of its entities, so broker/tests/m28_test.py can read what really happened on a real client. */
public final class RidesModule implements ServerModule {
	private ServerModuleContext context;
	private boolean crowding;
	private int crowdTurn;
	private SlotProp shownProp;
	private Beam beam;

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal("RIDE " + text), false);
	}

	private final class Boarding implements VehicleBehavior {
		private final String name;

		Boarding(String name) {
			this.name = name;
		}

		@Override
		public void tick(SlotVehicle vehicle) {
			// Once a second of the server's own time, which is what a speed can be measured against.
			if (vehicle.rider() != null && vehicle.tickCount % 20 == 0) {
				say(this.name + " at " + vehicle.getX() + " " + vehicle.getY() + " " + vehicle.getZ());
			}
		}

		@Override
		public InteractionResult interact(SlotVehicle vehicle, Player player, InteractionHand hand) {
			if (hand == InteractionHand.MAIN_HAND && player.getMainHandItem().is(Items.SLIME_BALL)) {
				vehicle.limitSpeed(0.5F);
				say(this.name + " held to half speed");
				return InteractionResult.SUCCESS;
			}
			return InteractionResult.PASS;
		}

		@Override
		public void boarded(SlotVehicle vehicle, ServerPlayer rider) {
			say(this.name + " boarded by " + rider.getName().getString());
		}

		@Override
		public void left(SlotVehicle vehicle, ServerPlayer rider) {
			say(this.name + " left by " + rider.getName().getString());
		}

		@Override
		public void hurt(SlotVehicle vehicle, DamageSource source) {
			say(this.name + " hurt by " + source.getMsgId());
		}
	}

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.bindItem("wand", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				SlotProjectile shot = context.shoot("bolt", player);
				say(shot == null ? "bolt refused" : "bolt fired for " + shot.damage());
				return InteractionResult.SUCCESS;
			}
		});
		context.bindProjectile("bolt", new ProjectileBehavior() {
			@Override
			public void hitEntity(SlotProjectile projectile, Entity target, boolean hurt) {
				say("bolt hit " + target.getType().toShortString() + " and " + (hurt ? "hurt it" : "did nothing") + ", shot by " + (projectile.getOwner() == null ? "nobody" : projectile.getOwner().getName().getString()));
			}

			@Override
			public void hitBlock(SlotProjectile projectile, BlockHitResult hit) {
				say("bolt hit block " + projectile.level().getBlockState(hit.getBlockPos()).getBlock().getName().getString());
			}

			@Override
			public void expired(SlotProjectile projectile) {
				say("bolt expired");
			}
		});
		context.bindVehicle("skiff", new Boarding("skiff"));
		context.bindVehicle("rover", new Boarding("rover"));
		context.bindVehicle("glider", new Boarding("glider"));
		context.bindProp("totem", new PropBehavior() {
			@Override
			public InteractionResult interact(SlotProp prop, Player player, InteractionHand hand) {
				if (hand == InteractionHand.MAIN_HAND) {
					say("totem clicked");
					prop.play("spin");
				}
				return InteractionResult.SUCCESS;
			}
		});
		// Each use does the next thing. A real client's hand is what uses it, so this is what a builder's own item would do.
		context.bindItem("show_wand", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				Vec3 at = player.position();
				if (RidesModule.this.shownProp == null) {
					RidesModule.this.shownProp = context.placeProp("totem", level, at.add(player.getViewVector(1.0F).multiply(1.0, 0.0, 1.0).scale(4.0)), player.getYRot() + 180.0F);
					say("totem placed");
				} else if (RidesModule.this.beam == null) {
					// A tall one to be seen from far off, and a slanted one that's only good for a few seconds.
					RidesModule.this.beam = context.beam(level, at.add(6.0, 0.0, 0.0), at.add(6.0, 180.0, 0.0), 1.0F, Blocks.REDSTONE_BLOCK.defaultBlockState(), 0);
					context.beam(level, at.add(-6.0, 0.0, 0.0), at.add(-30.0, 40.0, 0.0), 0.4F, Blocks.GOLD_BLOCK.defaultBlockState(), 15);
					say("beams drawn");
				} else {
					RidesModule.this.beam.remove();
					say("beam removed: " + RidesModule.this.beam.isRemoved());
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindItem("crowd_wand", new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				RidesModule.this.crowding = !RidesModule.this.crowding;
				say("crowd " + RidesModule.this.crowding);
				return InteractionResult.SUCCESS;
			}
		});
		// With nobody to hold to shots_per_second, the only limit on these is how many can be in the air at once.
		context.onServerTick(server -> {
			if (!this.crowding) {
				return;
			}
			ServerPlayer player = server.getPlayerList().getPlayers().getFirst();
			ServerLevel level = player.level();
			for (int i = 0; i < 10; i++) {
				double angle = this.crowdTurn++ * 0.7;
				context.shoot("swarm", level, player.position().add(0.0, 8.0, 0.0), new Vec3(Math.cos(angle), 0.02, Math.sin(angle)), null);
			}
		});
	}
}
