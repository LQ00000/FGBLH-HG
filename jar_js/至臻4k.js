// 从壳子内置目录加载cheerio 或者本地自备
import cheerio from 'assets://js/lib/cheerio.min.js';
// import cheerio from '../lib/cheerio.min.js';

//end 壳子内置的功能

import quarkApi, { getVideosFromShareLink, getPlayDatafromVideoInfo } from '../lib/quarkApi.js'
import { formatVideoName } from '../lib/utils.js'

const sites = [
    "https://mihdr.top",
    "https://www.miqk.cc",
    "https://www.mihdr.top"
]
const appConfig = {
    siteName: "至臻4k",
    siteUrl: sites[0],
}
async function init(ext) {
    const { quarkck } = ext
    const quarkCookie = await req(quarkck).content
    await quarkApi.setCookie(quarkCookie)
}

async function home(filter) {
    return JSON.stringify({
        class: [
            {
                type_id: "26",
                type_name: "臻彩"
            },
            {
                type_id: "1",
                type_name: "电影"
            },
            {
                type_id: "2",
                type_name: "剧集"
            },
            {
                type_id: "3",
                type_name: "综艺"
            },
            {
                type_id: "4",
                type_name: "动漫"
            },
            {
                type_id: "5",
                type_name: "短剧"
            }
        ]
    });

}

async function category(tid, pg, filter, extend) {

    try {
        if (!pg) pg = 1;
        const url = `${appConfig.siteUrl}/index.php/vod/show/id/${tid}/page/${pg}.html`;

        const res= await req(url)
        const html = await req(url).content;

        const $ = cheerio.load(html);

        let list = [];

        $('.module-item').each((i, el) => {

            const vod_id = $(el).find('.module-item-title').attr('href') || '';

            const vod_name = $(el).find('.module-item-title').attr('title')

            const vod_pic = $(el).find('img').attr('data-src')

            const vod_remarks = $(el).find('.module-item-text').text().trim();

            list.push({
                vod_id,
                vod_name,
                vod_pic,
                vod_remarks
            });
        });


        let pagecount = 1 ;
        const endPageEl = $('.module-footer .page-next').last()
        if(endPageEl.length > 0)
        {
            const endPage = parseInt(endPageEl.attr('href').match(/\d+/g)[1])
            pagecount = endPage
        }

        console.log("category list.length",list.length);
        console.log("category pagecount",pagecount);
        return JSON.stringify({
            list,
            pagecount: pagecount

        });
    } catch (e) {
        console.log(e)
        return JSON.stringify({ list: [] });    
     }
}

//根据网盘链接格式化剧集数据 格式化播放数据，生成 vod_play_from 和 vod_play_url 字段
async function formatVideoList(quarkLinks) {
    let playFromList = []; // 存放播放源名称，例如 ["夸克网盘#1", "夸克网盘#2"]
    let playUrlList = [];  // 存放对应的播放列表

    // 遍历每个分享链接，独立处理
    for (let i = 0; i < quarkLinks.length; i++) {
        const shareLink = quarkLinks[i];
        const { movieName, list: videos } = await getVideosFromShareLink(shareLink) || [];

        if (videos && videos.length > 0) {
            // 生成当前链接的播放列表字符串 (剧集1$url#剧集2$url)
            let currentLinkUrls = videos.map((v) => {
                let videoInfo = JSON.stringify(v);
                const videoName = formatVideoName(v.file_name, v.size);
                return `${videoName}\$${videoInfo}`;
            }).join("#");

            playUrlList.push(currentLinkUrls);
            // 如果有多个链接，加个后缀区分，方便用户选择
            playFromList.push(quarkLinks.length > 1 ? `夸克网盘#${i + 1}` : "夸克网盘");
        }
    }
    // 多个播放源用 $$$ 分隔，例如 "夸克网盘#1$$$夸克网盘#2"
    // 多个播放列表用 $$$ 分隔，例如 "剧集1$url1#剧集2$url1$$$剧集1$url2#剧集2$url2"
    return { vod_play_from: playFromList.join("$$$"), vod_play_url: playUrlList.join("$$$") };
}



/**
 * 2. 影视详情页 (在这里获取网页上的夸克分享链，并搜刮所有子集)
 */
async function detail(id) {
    try {
        let html = await req(`${appConfig.siteUrl}${id}`).content;
        const $ = cheerio.load(html);
        const quarkLinks = [];
        $('.module-row-one p').each((i, el) => {
            const text = $(el).text();
            // 只需要夸克
            if (text.includes('pan.quark.cn')) {
                quarkLinks.push(text);
            }
        });

        // 格式化播放数据，生成 vod_play_from 和 vod_play_url 字段
        const { vod_play_from, vod_play_url } = await formatVideoList(quarkLinks);

        let vod = {
            vod_id: id,
            vod_name: $(".page-title").text().trim(),
            // 多个播放源用 $$$ 分隔，例如 "夸克网盘#1$$$夸克网盘#2"
            vod_play_from: vod_play_from,
            // 多个播放列表用 $$$ 分隔，例如 "剧集1$url1#剧集2$url1$$$剧集1$url2#剧集2$url2"
            vod_play_url: vod_play_url,
            vod_pic: $(".video-cover img").attr("data-src"),
            vod_content: $(".video-info-item.video-info-content .sqjj_a").text().trim().replace(/\[收起部分\]/, ""),
        };
        return JSON.stringify({ list: [vod] });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

async function play(flag, id, flags) {
    const videoInfo = JSON.parse(id);
    const playObj = await getPlayDatafromVideoInfo(videoInfo)

    console.log("play", playObj)
    return JSON.stringify(playObj);
}

async function search(wd, quick) {


    try {
        // /index.php/vod/search.html?wd=
        const url = `${appConfig.siteUrl}/index.php/vod/search.html?wd=${encodeURIComponent(wd)}`;

        const html = await req(url).content;

        const $ = cheerio.load(html);
        let list = [];

        // 2. 定位搜索列表的外层容器节点
        $('.module-search-item').each((i, el) => {

            // 🚨 避坑核心：不要拿带 /play/ 的播放链接，要拿带有 /detail/ 的详情页链接！
            // 结构中 h3 -> a 标签或者 .video-serial 都是详情页链接
            const vod_id = $(el).find('h3 a').attr('href') || '';

            // 提取片名
            const vod_name = $(el).find('h3 a').text().trim() || '';

            const vod_pic = $(el).find('.module-item-pic img').attr('data-src') || '';
            // 提取更新状态 (例如："更新至142集")
            const vod_remarks = $(el).find('.video-serial').text().trim().replace("fuck you", "");
            if (vod_id && vod_name) {
                list.push({
                    vod_id,
                    vod_name,
                    vod_pic,
                    vod_remarks
                });
            }
        });
        return JSON.stringify({ list });

    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}




export default { init, home, category, detail, search, play };
