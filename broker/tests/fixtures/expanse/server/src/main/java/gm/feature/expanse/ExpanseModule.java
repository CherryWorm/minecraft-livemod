package gm.feature.expanse;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.RuinSpot;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;
import java.util.function.Consumer;
import java.util.stream.Stream;

/** Test fixture: says in chat what it hears and what it's told, so broker/tests/m30_test.py can read what really happened. */
public final class ExpanseModule implements ServerModule {
	private static final int LOOK_CHUNKS = 400;
	private static final int FROST_REACH = 8;
	private ServerModuleContext context;

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.listen(new WorldEvents() {
			@Override
			public void ruinPlaced(ServerLevel level, String ruin, BlockPos origin) {
				say("ruin placed: " + ruin + " at " + origin.toShortString() + " in " + level.dimension().identifier());
			}
		});
		door("expanse_key", player -> context.enterDimension(player, "moor"));
		door("expanse_home", context::leaveDimension);
		context.bindBlock("expanse_lens", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level instanceof ServerLevel server) {
					List<RuinSpot> spots = context.ruinsNear("great_hall", server, pos, LOOK_CHUNKS);
					// Those really there first, because that's what there's something to check against.
					say("ruins near: " + spots.size() + " " + Stream.concat(spots.stream().filter(RuinSpot::placed).limit(4), spots.stream().filter(spot -> !spot.placed()).limit(2))
							.map(spot -> "[" + spot.pos().toShortString() + " placed=" + spot.placed() + "]").toList());
				}
				return InteractionResult.SUCCESS;
			}
		});
		context.bindBlock("expanse_frost", new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level instanceof ServerLevel server) {
					int cells = context.setBiome(server, pos.offset(-FROST_REACH, -FROST_REACH, -FROST_REACH), pos.offset(FROST_REACH, FROST_REACH, FROST_REACH), "minecraft:snowy_plains");
					say("biome cells changed: " + cells);
				}
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void door(String item, Consumer<ServerPlayer> through) {
		this.context.bindItem(item, new ItemBehavior() {
			@Override
			public InteractionResult use(Level level, Player player, InteractionHand hand) {
				through.accept((ServerPlayer) player);
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void say(String text) {
		this.context.server().getPlayerList().broadcastSystemMessage(Component.literal(text), false);
	}
}
